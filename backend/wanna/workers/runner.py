"""A worker process that hosts exactly one Python model (diffusers or transformers).

Started by the model manager with CUDA_VISIBLE_DEVICES already set, so "cuda" here means
only the GPUs this model was assigned. Talks to the main server over local HTTP.
"""

from __future__ import annotations

import argparse
import hmac
import inspect
import json
import logging
import os
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

log = logging.getLogger("wanna.worker")

STATE = {"status": "loading", "error": None, "step": 0, "total_steps": 0, "busy": False, "device": None}
_run_lock = threading.Lock()
handler = None


# --- helpers ----------------------------------------------------------------

def _torch():
    import torch

    return torch


def _device_setup(gpu_count: int) -> str:
    torch = _torch()
    if torch.cuda.is_available() and gpu_count > 0:
        return "cuda"
    return "cpu"


def _dtype(device: str, prefer: str = "float16"):
    torch = _torch()
    if device == "cpu":
        return torch.float32
    if prefer == "bfloat16" and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float16


def _accepts(fn, params: dict) -> dict:
    """Keep only keyword arguments the pipeline's __call__ actually accepts."""
    sig = inspect.signature(fn)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        names = set(sig.parameters)
        # Pipelines with **kwargs still error on unknown keys in many cases, so be conservative.
        return {k: v for k, v in params.items() if k in names or k in ("prompt",)}
    return {k: v for k, v in params.items() if k in sig.parameters}


def _new_name(ext: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.{ext}"


def _decode_audio(path: str, sr: int = 16000):
    """Decode any audio/video file to mono float32 at `sr` using the bundled ffmpeg."""
    import imageio_ffmpeg
    import numpy as np

    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def _progress_cb(pipe, step, timestep, kwargs):
    STATE["step"] = step + 1
    return kwargs


# --- handlers ---------------------------------------------------------------

class Handler:
    def __init__(self, args):
        self.args = args
        self.out_dir = Path(args.outputs)
        self.device = _device_setup(args.gpu_count)
        STATE["device"] = self.device

    def run(self, params: dict) -> dict:
        raise NotImplementedError


class DiffusionHandler(Handler):
    """Text-to-image, image-to-image, text-to-video and image-to-video via diffusers."""

    def __init__(self, args):
        super().__init__(args)
        import diffusers

        torch = _torch()
        video = args.task == "video"
        dtype = _dtype(self.device, "bfloat16" if video else "float16")
        kw = {"torch_dtype": dtype}
        if args.variant and self.device == "cuda":
            kw["variant"] = args.variant

        multi_gpu = self.device == "cuda" and args.gpu_count > 1
        if multi_gpu:
            # Spread pipeline components (text encoder, unet/transformer, vae) across the assigned GPUs.
            kw["device_map"] = "balanced"

        pipe = None
        if not video:
            try:
                pipe = diffusers.AutoPipelineForText2Image.from_pretrained(args.path, **kw)
            except Exception:
                pipe = None
        if pipe is None:
            pipe = diffusers.DiffusionPipeline.from_pretrained(args.path, **kw)
        self.pipe = pipe

        if self.device == "cuda":
            # With device_map the components are already placed on their GPUs.
            if not multi_gpu:
                if args.offload:
                    pipe.enable_model_cpu_offload()
                else:
                    pipe.to("cuda")
            if video and hasattr(self.pipe, "vae") and hasattr(self.pipe.vae, "enable_tiling"):
                try:
                    self.pipe.vae.enable_tiling()
                except Exception:
                    pass
        self.img2img = None
        self.torch = torch
        # Remember the model's own scheduler so "builtin" can restore it, and cache swapped-in ones.
        self.builtin_scheduler = self.pipe.scheduler if hasattr(self.pipe, "scheduler") else None
        self.schedulers: dict[str, object] = {}
        self.sampler = "builtin"

    def _use_sampler(self, sampler: str | None) -> None:
        """Swap the pipeline's scheduler. Rejects samplers the model's scheduler family can't use."""
        from ..samplers import SAMPLERS

        sampler = sampler or "builtin"
        if sampler == self.sampler or self.builtin_scheduler is None:
            return
        if sampler == "builtin":
            sched = self.builtin_scheduler
        else:
            if sampler not in SAMPLERS:
                raise ValueError(f"Unknown sampler '{sampler}'")
            cls_name, extra, label = SAMPLERS[sampler]
            compatible = {c.__name__ for c in self.builtin_scheduler.compatibles}
            if cls_name not in compatible:
                raise ValueError(f"This model can't use the {label} sampler.")
            if sampler not in self.schedulers:
                import diffusers

                cls = getattr(diffusers, cls_name)
                self.schedulers[sampler] = cls.from_config(self.builtin_scheduler.config, **extra)
            sched = self.schedulers[sampler]
        self.pipe.scheduler = sched
        if self.img2img is not None:
            self.img2img.scheduler = sched
        self.sampler = sampler

    def run(self, p: dict) -> dict:
        torch = self.torch
        seed = p.get("seed")
        if seed is None or seed < 0:
            seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
        gen = torch.Generator(device="cpu").manual_seed(seed)
        steps = p.get("steps")
        call = {
            "prompt": p["prompt"],
            "negative_prompt": p.get("negative_prompt") or None,
            "width": p.get("width"),
            "height": p.get("height"),
            "num_inference_steps": steps,
            "guidance_scale": p.get("guidance"),
            "generator": gen,
            "callback_on_step_end": _progress_cb,
        }
        STATE["step"], STATE["total_steps"] = 0, steps or 0
        call = {k: v for k, v in call.items() if v is not None}
        init_image = None
        if p.get("image"):
            from PIL import Image

            init_image = Image.open(p["image"]).convert("RGB")

        if self.args.task == "video":
            call.update({"num_frames": p.get("num_frames"), "frame_rate": p.get("fps")})
            call = {k: v for k, v in call.items() if v is not None}
            if init_image is not None:
                call["image"] = init_image
            out = self.pipe(**_accepts(self.pipe.__call__, call))
            frames = out.frames[0]
            from diffusers.utils import export_to_video

            name = _new_name("mp4")
            export_to_video(frames, str(self.out_dir / name), fps=int(p.get("fps") or 16))
            return {"files": [name], "seed": seed}

        if p.get("sampler"):
            self._use_sampler(p["sampler"])
        pipe = self.pipe
        if init_image is not None:
            import diffusers

            if self.img2img is None:
                self.img2img = diffusers.AutoPipelineForImage2Image.from_pipe(self.pipe)
                self.img2img.scheduler = self.pipe.scheduler
            pipe = self.img2img
            call["image"] = init_image
            call["strength"] = p.get("strength", 0.6)
            call.pop("width", None)
            call.pop("height", None)
        files = []
        for _ in range(max(1, min(8, int(p.get("n") or 1)))):
            out = pipe(**_accepts(pipe.__call__, call))
            for img in out.images:
                name = _new_name("png")
                img.save(self.out_dir / name)
                files.append(name)
            seed += 1
            call["generator"] = torch.Generator(device="cpu").manual_seed(seed)
        return {"files": files, "seed": seed - len(files)}


class AudioGenHandler(Handler):
    """Text-to-speech and text-to-music/sound via the transformers text-to-audio pipeline."""

    def __init__(self, args):
        super().__init__(args)
        from transformers import pipeline

        dtype = _dtype(self.device) if self.device == "cuda" else None
        kw = {"model": args.path, "device": 0 if self.device == "cuda" else -1}
        if dtype is not None and args.task == "sound":
            kw["dtype"] = dtype
        self.pipe = pipeline("text-to-audio", **kw)
        self.is_bark = self.pipe.model.config.model_type == "bark"
        self.processor = None

    def _bark_with_voice(self, text: str, voice: str):
        """Bark voice presets must be loaded by its processor; the pipeline can't take a preset name."""
        import torch
        from transformers import AutoProcessor

        if self.processor is None:
            self.processor = AutoProcessor.from_pretrained(self.args.path)
        dev = self.pipe.model.device
        inputs = self.processor(text, voice_preset=voice)
        inputs = {
            k: v.to(dev) if hasattr(v, "to") else {kk: vv.to(dev) for kk, vv in v.items()} if isinstance(v, dict) else v
            for k, v in inputs.items()
        }
        with torch.no_grad():
            audio = self.pipe.model.generate(**inputs)
        return {"audio": audio.cpu().float().numpy(), "sampling_rate": self.pipe.model.generation_config.sample_rate}

    def run(self, p: dict) -> dict:
        import numpy as np
        import soundfile as sf

        text = p.get("text") or p.get("prompt") or ""
        STATE["step"], STATE["total_steps"] = 0, 0
        if self.args.task == "sound":
            seconds = float(p.get("duration") or 8)
            # MusicGen produces ~50 audio tokens per second.
            forward = {"do_sample": True, "max_new_tokens": int(min(30, max(1, seconds)) * 50)}
            out = self.pipe(text, forward_params=forward)
        elif self.is_bark and p.get("voice") and str(p["voice"]).startswith("v2/"):
            out = self._bark_with_voice(text, p["voice"])
        else:
            out = self.pipe(text)
        audio = np.asarray(out["audio"]).squeeze()
        if audio.ndim > 1:
            audio = audio.T if audio.shape[0] < audio.shape[1] else audio
        sr = int(out["sampling_rate"])
        speed = float(p.get("speed") or 1.0)
        if abs(speed - 1.0) > 0.01:
            import librosa

            audio = librosa.effects.time_stretch(audio.astype(np.float32), rate=speed)
        fmt = (p.get("format") or "wav").lower()
        ext = fmt if fmt in ("wav", "flac", "ogg") else "wav"
        name = _new_name(ext)
        sf.write(self.out_dir / name, audio.astype(np.float32), sr)
        if fmt == "mp3":
            name = _to_mp3(self.out_dir / name)
        return {"files": [name], "sampling_rate": sr, "duration": round(len(audio) / sr, 2)}


def _to_mp3(path: Path) -> str:
    import imageio_ffmpeg

    mp3 = path.with_suffix(".mp3")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-y", "-i", str(path), "-b:a", "192k", str(mp3)],
                   capture_output=True, check=True)
    path.unlink(missing_ok=True)
    return mp3.name


class TranscribeHandler(Handler):
    def __init__(self, args):
        super().__init__(args)
        from transformers import pipeline

        kw = {"model": args.path, "device": 0 if self.device == "cuda" else -1}
        if self.device == "cuda":
            kw["dtype"] = _dtype(self.device)
        self.pipe = pipeline("automatic-speech-recognition", **kw)

    def run(self, p: dict) -> dict:
        audio = _decode_audio(p["file"])
        gen = {}
        if p.get("language"):
            gen["language"] = p["language"]
        if p.get("translate"):
            gen["task"] = "translate"
        kind = getattr(self.pipe, "type", "")
        if kind == "seq2seq_whisper":
            # Whisper gives sentence-level timestamps and handles long audio in 30 s windows.
            kwargs = {"chunk_length_s": 30, "return_timestamps": True}
            if gen:
                kwargs["generate_kwargs"] = gen
        elif kind.startswith("ctc"):
            kwargs = {"chunk_length_s": 30}  # CTC models (wav2vec2 etc.) chunk fine but have no sentence timestamps
        else:
            kwargs = {}  # other seq2seq models (e.g. Moonshine) take the audio as is
        STATE["step"], STATE["total_steps"] = 0, 0
        out = self.pipe({"raw": audio, "sampling_rate": 16000}, **kwargs)
        segments = [
            {"start": c["timestamp"][0], "end": c["timestamp"][1], "text": c["text"].strip()}
            for c in out.get("chunks", [])
            if c.get("timestamp")
        ]
        return {"text": out["text"].strip(), "segments": segments, "duration": round(len(audio) / 16000, 2)}


class ChatHandler(Handler):
    """Fallback chat for safetensors LLMs that have no GGUF build."""

    def __init__(self, args):
        super().__init__(args)
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(args.path)
        kw = {"dtype": _dtype(self.device, "bfloat16")}
        if self.device == "cuda":
            kw["device_map"] = "auto"  # spreads across all visible (assigned) GPUs
        self.model = AutoModelForCausalLM.from_pretrained(args.path, **kw)

    def _inputs(self, p):
        msgs = [{"role": m["role"], "content": _text_content(m.get("content"))} for m in p["messages"]]
        ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True)
        return {k: v.to(self.model.device) for k, v in ids.items()}

    def _gen_kwargs(self, p):
        temp = p.get("temperature", 0.7)
        kw = {"max_new_tokens": int(p.get("max_tokens") or 1024)}
        if temp and temp > 0:
            kw.update(do_sample=True, temperature=temp, top_p=p.get("top_p", 0.95))
        else:
            kw["do_sample"] = False
        return kw

    def run(self, p: dict) -> dict:
        inputs = self._inputs(p)
        out = self.model.generate(**inputs, **self._gen_kwargs(p))
        new = out[0][inputs["input_ids"].shape[1]:]
        return {"text": self.tok.decode(new, skip_special_tokens=True),
                "prompt_tokens": int(inputs["input_ids"].shape[1]), "completion_tokens": int(len(new))}

    def stream(self, p: dict):
        from transformers import TextIteratorStreamer

        inputs = self._inputs(p)
        streamer = TextIteratorStreamer(self.tok, skip_prompt=True, skip_special_tokens=True)
        t = threading.Thread(target=self.model.generate, kwargs={**inputs, **self._gen_kwargs(p), "streamer": streamer})
        t.start()
        for piece in streamer:
            if piece:
                yield piece
        t.join()


def _text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


HANDLERS = {
    "image": DiffusionHandler,
    "video": DiffusionHandler,
    "speech": AudioGenHandler,
    "sound": AudioGenHandler,
    "transcribe": TranscribeHandler,
    "chat": ChatHandler,
}


# --- server -----------------------------------------------------------------

app = FastAPI()
TOKEN = os.environ.get("WANNA_WORKER_TOKEN", "")


def _authorized(request: Request) -> None:
    """Only wanna.sh, which started this worker and knows its secret, may run the model."""
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if TOKEN and not hmac.compare_digest(given, TOKEN):
        raise HTTPException(401, "Missing or wrong worker token")


@app.get("/health")
def health():
    return STATE


@app.post("/run", dependencies=[Depends(_authorized)])
def run(params: dict):
    if STATE["status"] != "ready":
        raise HTTPException(503, STATE.get("error") or "Model is still loading")
    with _run_lock:
        STATE["busy"] = True
        try:
            return handler.run(params)
        except Exception as e:
            log.error(traceback.format_exc())
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        finally:
            STATE["busy"] = False
            _free_cache()


@app.post("/stream", dependencies=[Depends(_authorized)])
def stream(params: dict):
    if STATE["status"] != "ready" or not hasattr(handler, "stream"):
        raise HTTPException(503, "Streaming not available")

    def gen():
        with _run_lock:
            STATE["busy"] = True
            try:
                for piece in handler.stream(params):
                    yield json.dumps({"text": piece}) + "\n"
            except Exception as e:
                yield json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n"
            finally:
                STATE["busy"] = False

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _free_cache():
    try:
        torch = _torch()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _load(args):
    global handler
    try:
        handler = HANDLERS[args.task](args)
        STATE["status"] = "ready"
    except Exception as e:
        log.error(traceback.format_exc())
        STATE["status"], STATE["error"] = "error", f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=list(HANDLERS))
    ap.add_argument("--path", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--outputs", required=True)
    ap.add_argument("--variant", default=None)
    ap.add_argument("--gpu-count", type=int, default=0)
    ap.add_argument("--offload", action="store_true", help="Keep weights in RAM and stream them to the GPU")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=_load, args=(args,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
