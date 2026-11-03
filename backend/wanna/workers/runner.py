"""A worker process that hosts exactly one model: diffusers or transformers in Python, or a picture model on
stable-diffusion.cpp's library, loaded into this process (see SdCppHandler).

Started by the model manager with CUDA_VISIBLE_DEVICES already set, so "cuda" here means
only the GPUs this model was assigned. On a Mac with Apple Silicon, "mps" is its built-in GPU.
Talks to the main server over local HTTP.
"""

from __future__ import annotations

import argparse
import hmac
import inspect
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

log = logging.getLogger("wanna.worker")

# phase (stable-diffusion.cpp only): "preparing" (loading the model's parts, reading the description), "drawing"
# (the steps), "finishing" (decoding the picture). None for other engines.
STATE = {"status": "loading", "error": None, "step": 0, "total_steps": 0, "busy": False, "device": None,
         "phase": None}
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
    if gpu_count > 0 and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _dtype(device: str, prefer: str = "float16"):
    torch = _torch()
    if device == "cpu":
        return torch.float32
    # PyTorch uses the Apple GPU from macOS 15, which supports bfloat16 (it arrived in macOS 14).
    if prefer == "bfloat16" and (device == "mps" or torch.cuda.is_bf16_supported()):
        return torch.bfloat16
    return torch.float16


def _pipeline_device(device: str):
    """The device argument for a transformers pipeline: GPU 0, the Apple GPU, or -1 for the processor."""
    return {"cuda": 0, "mps": "mps"}.get(device, -1)


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
        if args.variant:
            # Only this variant's files were downloaded. On the processor diffusers converts them to float32.
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
        elif self.device == "mps":
            # The GPU shares the Mac's memory, so moving parts on and off it (memory saver) wouldn't save any.
            pipe.to("mps")
        if self.device != "cpu" and video and hasattr(self.pipe, "vae") and hasattr(self.pipe.vae, "enable_tiling"):
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
        self.lora: str | None = None  # the trained style (LoRA folder) loaded now, if any

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

    def _use_lora(self, path: str | None, strength: float) -> None:
        """Load, swap or drop a trained style (a LoRA from Train). It stays loaded between pictures."""
        if path != self.lora:
            if self.lora:
                self.pipe.unload_lora_weights()
            if path:
                self.pipe.load_lora_weights(path, weight_name="pytorch_lora_weights.safetensors", adapter_name="trained")
            self.lora = path
        if path:
            self.pipe.set_adapters(["trained"], adapter_weights=[strength])

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
        self._use_lora(p.get("lora_path"), float(p.get("lora_strength") or 1.0))
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

        dtype = _dtype(self.device) if self.device != "cpu" else None
        kw = {"model": args.path, "device": _pipeline_device(self.device)}
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

        kw = {"model": args.path, "device": _pipeline_device(self.device)}
        if self.device != "cpu":
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
        if self.device == "mps":
            self.model.to("mps")

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


class SdCppHandler:
    """Pictures from GGUF models on stable-diffusion.cpp, through its C library loaded into this process. The model
    stays loaded between pictures, and nothing but this token-protected worker can reach it. No PyTorch needed.

    Models that edit (Qwen-Image 2.1, Qwen-Image-Edit) take attached pictures as references and follow an
    instruction ("make the sky purple", "the person in picture 1 and the person in picture 2 at a cafe"). With one
    picture the result keeps its shape; with several, the requested shape, or picture 1's with keep_shape. Others start
    from one attached picture and redraw it (image to image, with a strength)."""

    def __init__(self, args):
        import ctypes as C
        from collections import deque

        from . import sdcpp_lib as L

        self.C, self.L = C, L
        self.args = args
        self.out_dir = Path(args.outputs)
        self.cfg = json.loads(args.sdcpp)
        self.errors: deque[str] = deque(maxlen=20)
        lib = self.lib = L.load(self.cfg["lib_dir"])
        L.check_layout(lib)

        def on_log(level, text, _data):
            msg = (text or b"").decode("utf-8", "replace").rstrip()
            if not msg:
                return
            if level >= 3:
                self.errors.append(msg)
            # Debug and verbose lines would flood the log; progress comes from the progress callback instead.
            if level >= 2:
                name = L.LOG_LEVELS[level] if level < len(L.LOG_LEVELS) else level
                print(f"[sd.cpp {name}] {msg}", flush=True)

        def on_progress(step, steps, _time, _data):
            # The same callback reports loading the model's parts (counted in tensors, the first time each is used)
            # and decoding as well as drawing. Only a count matching the requested steps is the drawing.
            if self.expected_steps and steps == self.expected_steps:
                STATE["step"], STATE["total_steps"], STATE["phase"] = step, steps, "drawing"
            elif STATE["phase"] == "drawing" and STATE["step"] >= STATE["total_steps"]:
                STATE["phase"] = "finishing"

        self.expected_steps = 0

        # Kept on self: ctypes callbacks must outlive every call into the library.
        self._log_cb, self._progress_cb = L.LOG_CB(on_log), L.PROGRESS_CB(on_progress)
        lib.sd_set_log_callback(self._log_cb, None)
        lib.sd_set_progress_callback(self._progress_cb, None)

        p = L.sd_ctx_params_t()
        lib.sd_ctx_params_init(C.byref(p))
        parts = self.cfg["parts"]
        self._keep = []  # bytes whose pointers the library holds on to

        def text(v):
            b = v.encode() if v else None
            self._keep.append(b)
            return b

        p.diffusion_model_path = text(parts["diffusion"])
        p.llm_path = text(parts.get("llm"))
        p.llm_vision_path = text(parts.get("vision"))
        p.vae_path = text(parts.get("vae"))
        p.model_args = text(self.cfg.get("model_args"))
        # Weights the graphics card can't hold go to system memory or the drive (stable-diffusion.cpp's auto-fit, on
        # by default). Memory-mapping lets the system drop pages and read them again when it needs the room.
        p.enable_mmap = True
        STATE["device"] = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") else "cpu"
        self.ctx = lib.new_sd_ctx(C.byref(p))
        if not self.ctx:
            raise RuntimeError(self._error("Couldn't load the model."))
        if not lib.sd_ctx_supports_image_generation(self.ctx):
            raise RuntimeError("This model can't make pictures.")
        # Names the library doesn't know come back as the enum's count: leave those to the library's default.
        method, scheduler = self.cfg.get("sample_method"), self.cfg.get("scheduler")
        self.sample_method = lib.str_to_sample_method(method.encode()) if method else None
        if self.sample_method is not None and self.sample_method >= L.SAMPLE_METHOD_COUNT:
            self.sample_method = None
        self.scheduler = lib.str_to_scheduler(scheduler.encode()) if scheduler else None
        if self.scheduler is not None and self.scheduler >= L.SCHEDULER_COUNT:
            self.scheduler = None
        print(f"Loaded {lib.sd_get_model_version_name(self.ctx).decode()} on stable-diffusion.cpp "
              f"{lib.sd_commit().decode()}", flush=True)

    def _error(self, fallback: str) -> str:
        msg = next((e for e in reversed(self.errors) if e), "")
        if "out of memory" in msg.lower():
            return "Not enough memory for this model. Try a smaller version, or stop other models first."
        return msg[-400:] or fallback

    def _image(self, path: str):
        """An sd_image_t over the picture's pixels (RGB, or RGBA when it has transparency), and the buffer behind it."""
        from PIL import Image, ImageOps

        C, L = self.C, self.L
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            mode = "RGBA" if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info else "RGB"
            im = im.convert(mode)
            w, h = im.size
            data = im.tobytes()
        buf = (C.c_uint8 * len(data)).from_buffer_copy(data)
        img = L.sd_image_t(width=w, height=h, channel=len(mode), data=C.cast(buf, C.POINTER(C.c_uint8)))
        return img, buf

    @staticmethod
    def _fit(w: int, h: int, area: int) -> tuple[int, int]:
        """A size with the picture's shape and about `area` pixels, sides multiples of 32 (as these models need)."""
        scale = (area / (w * h)) ** 0.5
        return max(256, round(w * scale / 32) * 32), max(256, round(h * scale / 32) * 32)

    def run(self, p: dict) -> dict:
        import random

        from PIL import Image

        C, L, lib = self.C, self.L, self.lib
        paths = p.get("images") or ([p["image"]] if p.get("image") else [])
        edits, makes = self.cfg.get("edits"), self.cfg.get("makes", True)
        if len(paths) > 1 and not edits:
            raise ValueError("This model starts from one picture.")
        if not paths and not makes:
            raise ValueError("This model changes pictures you give it. Attach a picture and describe the change.")

        g = L.sd_img_gen_params_t()
        lib.sd_img_gen_params_init(C.byref(g))
        prompt = (p.get("prompt") or "").encode()
        negative = (p.get("negative_prompt") or "").encode()
        g.prompt, g.negative_prompt = prompt, negative
        width = max(256, int(p.get("width") or 1024) // 32 * 32)
        height = max(256, int(p.get("height") or 1024) // 32 * 32)
        keep = []  # pixel buffers the library reads during the call
        if paths:
            loaded = [self._image(path) for path in paths]
            keep += loaded
            first = loaded[0][0]
            if edits:
                # Follow the instruction with the pictures as references, in order ("picture 1", "picture 2"...).
                refs = (L.sd_image_t * len(loaded))(*(img for img, _ in loaded))
                keep.append(refs)
                g.ref_images, g.ref_images_count = refs, len(loaded)
            else:
                g.init_image = first
                g.strength = float(p.get("strength") or 0.6)
            if len(paths) == 1 or p.get("keep_shape"):
                # Keep the (first) picture's shape, at about the requested number of pixels.
                width, height = self._fit(first.width, first.height, width * height)
        g.width, g.height = width, height
        sp = g.sample_params
        if p.get("steps"):
            sp.sample_steps = int(p["steps"])
        if p.get("guidance") is not None:
            sp.guidance.txt_cfg = float(p["guidance"])
        if self.sample_method is not None:
            sp.sample_method = self.sample_method
        if self.scheduler is not None:
            sp.scheduler = self.scheduler
        if self.cfg.get("flow_shift"):
            sp.flow_shift = float(self.cfg["flow_shift"])
        seed = p.get("seed")
        if seed is None or int(seed) < 0:
            seed = random.randint(0, 2**31 - 1)
        g.seed = int(seed)
        g.batch_count = max(1, min(8, int(p.get("n") or 1)))

        STATE["step"], STATE["total_steps"], STATE["phase"] = 0, sp.sample_steps, "preparing"
        self.expected_steps = sp.sample_steps
        self.errors.clear()
        result = C.POINTER(L.sd_image_generation_result_t)()
        try:
            ok = lib.generate_image(self.ctx, C.byref(g), C.byref(result))
        finally:
            STATE["phase"], self.expected_steps = None, 0
        if not ok or not result:
            raise RuntimeError(self._error("The picture couldn't be made."))
        files = []
        try:
            res = result.contents
            for i in range(res.count):
                im = res.items[i].image
                if not im.data:
                    continue
                mode = {1: "L", 3: "RGB", 4: "RGBA"}[im.channel]
                data = C.string_at(im.data, im.width * im.height * im.channel)
                name = _new_name("png")
                pic = Image.frombytes(mode, (im.width, im.height), data)
                if mode == "RGBA" and pic.getchannel("A").getextrema()[0] >= 250:
                    # Qwen-Image 2.1 always returns an alpha channel; unless transparency was asked for, it's solid
                    # apart from rounding (253, 254), so save a plain picture.
                    pic = pic.convert("RGB")
                pic.save(self.out_dir / name)
                files.append(name)
        finally:
            lib.free_sd_image_generation_result(result)
        if not files:
            raise RuntimeError(self._error("The picture couldn't be made."))
        return {"files": files, "seed": int(seed), "width": width, "height": height}


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
    if "torch" not in sys.modules:
        return  # stable-diffusion.cpp workers don't use PyTorch; importing it here would only cost memory
    try:
        torch = _torch()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def _load(args):
    global handler
    try:
        handler = SdCppHandler(args) if args.engine == "sdcpp" else HANDLERS[args.task](args)
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
    ap.add_argument("--engine", default=None, help="sdcpp: a picture model on stable-diffusion.cpp")
    ap.add_argument("--sdcpp", default=None, help="JSON: library folder, model files and settings")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=_load, args=(args,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
