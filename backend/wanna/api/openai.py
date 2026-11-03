"""OpenAI-compatible endpoints under /v1, so any OpenAI SDK or tool can point at wanna.sh."""

from __future__ import annotations

import base64
import json
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

from .. import db, imagefamilies, jobs, presets, training
from ..config import OUTPUTS_DIR, UPLOADS_DIR
from ..workers.manager import LoadError, ModelNotFound, manager
from . import tool_loop
from .auth import require_key

router = APIRouter(prefix="/v1", dependencies=[Depends(require_key)])

AUDIO_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg", "opus": "audio/ogg"}


def _err(status: int, message: str, code: str = "invalid_request_error") -> HTTPException:
    return HTTPException(status, detail={"error": {"message": message, "type": code, "code": code}})


def _resolve(model: str | None, task: str) -> dict:
    try:
        return manager.resolve(model, task)
    except ModelNotFound as e:
        raise _err(404, str(e), "model_not_found")


async def _ready(model: dict):
    try:
        return await manager.ensure_ready(model)
    except LoadError as e:
        raise _err(503, str(e), "model_load_failed")


def _file_url(request: Request, name: str) -> str:
    return str(request.base_url).rstrip("/") + f"/files/{name}"


# --- models -----------------------------------------------------------------

@router.get("/models")
def list_models():
    loaded = {w["id"]: w for w in manager.loaded()}
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": int(m["created_at"]),
                "owned_by": m["repo_id"].split("/")[0],
                "wanna": {"task": m["task"], "repo_id": m["repo_id"], "engine": m["engine"],
                          "loaded": m["id"] in loaded},
            }
            for m in db.list_models()
        ],
    }


@router.get("/models/{model_id:path}")
def get_model(model_id: str):
    m = db.get_model(model_id)
    if not m:
        raise _err(404, f"Model '{model_id}' is not installed.", "model_not_found")
    return {"id": m["id"], "object": "model", "created": int(m["created_at"]), "owned_by": m["repo_id"].split("/")[0]}


# --- chat -------------------------------------------------------------------

@router.post("/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    wanted = body.pop("wanna_tools", None)  # wanna.sh runs its custom tools itself (see tool_loop.py)
    model = _resolve(body.get("model"), "chat")
    if wanted and model["engine"] != "llamacpp":
        raise _err(400, "wanna_tools needs a GGUF chat model (the kind that runs on llama.cpp).")
    worker = await _ready(model)
    body["model"] = model["id"]

    if wanted:
        return await tool_loop.run(worker.url + "/v1/chat/completions", worker.headers, body, wanted)
    if model["engine"] == "llamacpp":
        return await _proxy(worker.url + "/v1/chat/completions", body, worker.headers)
    return await _transformers_chat(worker, model, body)


@router.post("/completions")
async def completions(request: Request):
    body = await request.json()
    model = _resolve(body.get("model"), "chat")
    if model["engine"] != "llamacpp":
        raise _err(400, "Text completions are only available for GGUF chat models. Use /v1/chat/completions.")
    worker = await _ready(model)
    body["model"] = model["id"]
    return await _proxy(worker.url + "/v1/completions", body, worker.headers)


async def _proxy(url: str, body: dict, headers: dict):
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), headers=headers)
    if body.get("stream"):
        req = client.build_request("POST", url, json=body)
        r = await client.send(req, stream=True)
        if r.status_code != 200:
            text = await r.aread()
            await client.aclose()
            return Response(text, status_code=r.status_code, media_type="application/json")

        async def gen():
            try:
                async for chunk in r.aiter_raw():
                    yield chunk
            finally:
                await r.aclose()
                await client.aclose()

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    try:
        r = await client.post(url, json=body)
    finally:
        await client.aclose()
    return Response(r.content, status_code=r.status_code, media_type="application/json")


async def _transformers_chat(worker, model: dict, body: dict):
    cid = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    if not body.get("stream"):
        async with httpx.AsyncClient(timeout=None) as c:
            r = await c.post(worker.url + "/run", json=body, headers=worker.headers)
        if r.status_code != 200:
            raise _err(r.status_code, r.text)
        out = r.json()
        return {
            "id": cid, "object": "chat.completion", "created": created, "model": model["id"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": out["text"]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": out["prompt_tokens"], "completion_tokens": out["completion_tokens"],
                      "total_tokens": out["prompt_tokens"] + out["completion_tokens"]},
        }

    async def gen():
        def chunk(delta, finish=None):
            return "data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk", "created": created, "model": model["id"],
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }) + "\n\n"

        yield chunk({"role": "assistant", "content": ""})
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", worker.url + "/stream", json=body, headers=worker.headers) as r:
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    piece = json.loads(line)
                    if "error" in piece:
                        yield "data: " + json.dumps({"error": {"message": piece["error"]}}) + "\n\n"
                        break
                    yield chunk({"content": piece["text"]})
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- images -----------------------------------------------------------------

def _size(size: str | None) -> tuple[int | None, int | None]:
    if not size or size == "auto" or "x" not in size:
        return None, None
    w, h = size.lower().split("x", 1)
    return int(w), int(h)


def _image_payload(request: Request, job, response_format: str | None):
    if job.status != "completed":
        raise _err(500, job.error or "Image generation failed", "generation_failed")
    data = []
    for name in job.result["files"]:
        if response_format == "b64_json":
            data.append({"b64_json": base64.b64encode((OUTPUTS_DIR / name).read_bytes()).decode(),
                         "revised_prompt": job.prompt})
        else:
            data.append({"url": _file_url(request, name), "revised_prompt": job.prompt})
    return {"created": int(job.created_at), "data": data}


@router.post("/images/generations")
async def images_generations(request: Request):
    body = await request.json()
    model = _resolve(body.get("model"), "image")
    if (model.get("meta") or {}).get("needs_image"):
        raise _err(400, f"{model['id']} changes pictures you give it and can't start from a description alone. "
                        "Use POST /v1/images/edits with a picture.")
    w, h = _size(body.get("size"))
    params = presets.apply(model, {
        "prompt": body["prompt"],
        "negative_prompt": body.get("negative_prompt"),
        "n": body.get("n", 1),
        "width": w, "height": h,
        "steps": body.get("steps") or body.get("num_inference_steps"),
        "guidance": body.get("guidance_scale"),
        "seed": body.get("seed"),
        "sampler": body.get("sampler"),
        "quality": {"low": "fast", "medium": "balanced", "high": "best", "hd": "best", "standard": "balanced"}
        .get(body.get("quality") or "", body.get("quality")),
    })
    try:  # a trained style: {"lora": "<id from /api/training>", "lora_strength": 0.8}
        params = training.apply(model, {**params, "lora": body.get("lora"), "lora_strength": body.get("lora_strength")})
    except training.TrainError as e:
        raise _err(400, str(e))
    job = await jobs.run_now("image", model, params, body["prompt"])
    return _image_payload(request, job, body.get("response_format"))


@router.post("/images/edits")
async def images_edits(request: Request):
    """One picture, or several to combine (OpenAI's SDKs send a list as repeated "image[]" fields; "image" repeated
    works too). Models that take one picture refuse more."""
    form = await request.form()
    uploads = [f for key in ("image", "image[]") for f in form.getlist(key) if hasattr(f, "read")]
    prompt = form.get("prompt")
    if not uploads:
        raise _err(400, "Attach a picture as 'image'.")
    if not prompt:
        raise _err(400, "'prompt' is required.")

    def number(key, cast, default):
        try:
            return cast(form[key]) if form.get(key) not in (None, "") else default
        except ValueError:
            raise _err(400, f"'{key}' should be a number.") from None

    m = _resolve(form.get("model"), "image")
    problem = imagefamilies.too_many_pictures(m, len(uploads))
    if problem:
        raise _err(400, problem)
    paths = [str(_save_upload(f)) for f in uploads]
    params = {"prompt": prompt, "n": number("n", int, 1), "image": paths[0], "images": paths,
              "strength": number("strength", float, 0.6), "seed": number("seed", int, None)}
    if form.get("size") and form["size"] != "auto":
        params["width"], params["height"] = _size(form["size"])
    params = presets.apply(m, params)
    job = await jobs.run_now("image", m, params, prompt)
    return _image_payload(request, job, form.get("response_format"))


def _save_upload(f: UploadFile) -> Path:
    ext = Path(f.filename or "upload").suffix or ".bin"
    path = UPLOADS_DIR / f"{uuid.uuid4().hex}{ext}"
    with open(path, "wb") as out:
        out.write(f.file.read())
    return path


# --- audio ------------------------------------------------------------------

@router.post("/audio/speech")
async def audio_speech(request: Request):
    body = await request.json()
    model = _resolve(body.get("model"), "speech")
    fmt = body.get("response_format", "mp3")
    params = {"text": body["input"], "voice": body.get("voice"), "speed": body.get("speed", 1.0),
              "format": "mp3" if fmt not in ("wav", "flac", "ogg") else fmt}
    job = await jobs.run_now("speech", model, params, body["input"])
    if job.status != "completed":
        raise _err(500, job.error or "Speech generation failed", "generation_failed")
    name = job.result["files"][0]
    return FileResponse(OUTPUTS_DIR / name, media_type=AUDIO_TYPES.get(name.rsplit(".", 1)[-1], "audio/wav"))


async def _transcribe(request, file, model, language, response_format, translate):
    m = _resolve(model if model and model != "whisper-1" else None, "transcribe")
    path = _save_upload(file)
    job = await jobs.run_now("transcribe", m, {"file": str(path), "language": language, "translate": translate},
                             file.filename or "")
    path.unlink(missing_ok=True)
    if job.status != "completed":
        raise _err(500, job.error or "Transcription failed", "transcription_failed")
    r = job.result
    fmt = response_format or "json"
    if fmt == "text":
        return PlainTextResponse(r["text"])
    if fmt in ("srt", "vtt"):
        return PlainTextResponse(_subtitles(r["segments"], fmt))
    if fmt == "verbose_json":
        return {"task": "translate" if translate else "transcribe", "language": language, "duration": r["duration"],
                "text": r["text"],
                "segments": [{"id": i, "start": s["start"], "end": s["end"], "text": s["text"]}
                             for i, s in enumerate(r["segments"])]}
    return {"text": r["text"]}


@router.post("/audio/transcriptions")
async def audio_transcriptions(
    request: Request, file: UploadFile = File(...), model: str | None = Form(None),
    language: str | None = Form(None), response_format: str | None = Form(None),
):
    return await _transcribe(request, file, model, language, response_format, False)


@router.post("/audio/translations")
async def audio_translations(
    request: Request, file: UploadFile = File(...), model: str | None = Form(None),
    response_format: str | None = Form(None),
):
    return await _transcribe(request, file, model, None, response_format, True)


def _subtitles(segments: list[dict], fmt: str) -> str:
    def ts(t):
        t = t or 0
        h, rem = divmod(t, 3600)
        m, s = divmod(rem, 60)
        sep = "," if fmt == "srt" else "."
        return f"{int(h):02}:{int(m):02}:{int(s):02}{sep}{int((s % 1) * 1000):03}"

    lines = ["WEBVTT", ""] if fmt == "vtt" else []
    for i, s in enumerate(segments, 1):
        if fmt == "srt":
            lines.append(str(i))
        lines += [f"{ts(s['start'])} --> {ts(s['end'] if s['end'] is not None else s['start'])}", s["text"], ""]
    return "\n".join(lines)


# --- video (mirrors OpenAI's async /v1/videos jobs) --------------------------

def _video_obj(job) -> dict:
    status = {"queued": "queued", "loading": "queued", "running": "in_progress",
              "completed": "completed", "failed": "failed"}[job.status]
    p = job.params
    fps = p.get("fps") or 16
    return {
        "id": job.id,
        "object": "video",
        "model": job.model["id"],
        "status": status,
        "progress": int(job.to_dict()["progress"] * 100),
        "prompt": job.prompt,
        "created_at": int(job.created_at),
        "completed_at": int(job.completed_at) if job.completed_at else None,
        "seconds": str(round((p.get("num_frames") or 0) / fps, 1)),
        "size": f"{p.get('width')}x{p.get('height')}",
        "error": {"code": "generation_failed", "message": job.error} if job.error else None,
    }


@router.post("/videos")
async def create_video(request: Request):
    ctype = request.headers.get("content-type", "")
    image_path = None
    if ctype.startswith("multipart/"):
        form = await request.form()
        body = {k: v for k, v in form.items() if not hasattr(v, "filename")}
        ref = form.get("input_reference")
        if ref is not None and hasattr(ref, "filename"):
            image_path = str(_save_upload(ref))
    else:
        body = await request.json()
    model = _resolve(body.get("model"), "video")
    w, h = _size(body.get("size"))
    base = presets.for_model(model)
    fps = base.get("fps", 16)
    frames = int(float(body["seconds"]) * fps) + 1 if body.get("seconds") else None
    params = presets.apply(model, {
        "prompt": body["prompt"], "width": w, "height": h, "num_frames": frames,
        "negative_prompt": body.get("negative_prompt"), "seed": _int(body.get("seed")),
        "steps": _int(body.get("steps")), "image": image_path,
    })
    job = jobs.submit("video", model, params, body["prompt"])
    return _video_obj(job)


def _int(v):
    return int(v) if v not in (None, "") else None


@router.get("/videos/{video_id}")
def get_video(video_id: str):
    job = jobs.get(video_id)
    if not job or job.task != "video":
        raise _err(404, "Video not found", "not_found")
    return _video_obj(job)


@router.get("/videos/{video_id}/content")
def get_video_content(video_id: str):
    job = jobs.get(video_id)
    if job and job.status == "completed":
        return FileResponse(OUTPUTS_DIR / job.result["files"][0], media_type="video/mp4")
    gen = db.get_generation(video_id)
    if gen and gen["files"]:
        return FileResponse(OUTPUTS_DIR / gen["files"][0], media_type="video/mp4")
    raise _err(404, "Video not ready", "not_found")


@router.post("/embeddings")
async def embeddings(request: Request):
    """Vectors from an installed search (embedding) model. With a text-only model, text is embedded exactly as sent.
    A model that can see pictures also takes pictures, and puts every input in its own format (see _picture_items)."""
    body = await request.json()
    model = _resolve(body.get("model"), "embed")
    from ..knowledge.families import sees_pictures

    if sees_pictures(model):
        return await _picture_embeddings(model, body)
    if _picture_items(body.get("input"), check_only=True):
        raise _err(400, f"{model['id']} reads text only. For pictures, use a search model that can see them, such as "
                        "Qwen3 VL Embedding.")
    worker = await _ready(model)
    body["model"] = model["id"]
    return await _proxy(worker.url + "/v1/embeddings", body, worker.headers)


def _picture_items(inputs, check_only: bool = False):
    """Embedding inputs as items for knowledge.embed: text, or {"image", "text"}. An input is a string, an
    {"type": "image_url", "image_url": {"url": "data:..."}} or {"type": "text", "text": ...} part, an {"image": base64}
    object, or a list of parts (a picture with words about it). With check_only, just whether there are pictures."""
    from ..knowledge.pictures import PictureError, from_data_url

    inputs = inputs if isinstance(inputs, list) else [inputs]
    out, any_picture = [], False
    for n, item in enumerate(inputs):
        parts = item if isinstance(item, list) else [item]
        text, image = [], None
        for part in parts:
            if isinstance(part, str):
                text.append(part)
                continue
            if not isinstance(part, dict):
                raise _err(400, f"input {n}: each input is text, a picture or a list of them.")
            url = (part.get("image_url") or {}).get("url") if isinstance(part.get("image_url"), dict) else part.get("image_url")
            raw = part.get("image") or url
            if part.get("type") == "text" or "text" in part and not raw:
                text.append(str(part.get("text") or ""))
            elif raw:
                any_picture = True
                if check_only:
                    continue
                if part.get("text"):  # {"image": ..., "text": "words about it"}
                    text.append(str(part["text"]))
                if image is not None:
                    raise _err(400, f"input {n}: one picture per input.")
                if str(raw).startswith(("http://", "https://")):
                    raise _err(400, f"input {n}: send the picture itself, as a data URL or base64, not a web address.")
                try:
                    from ..knowledge.embed import picture

                    image = picture(from_data_url(str(raw)))["image"]
                except PictureError as e:
                    raise _err(400, f"input {n}: {e}")
            else:
                raise _err(400, f"input {n}: a part needs text, image_url or image.")
        if not check_only:
            joined = "\n".join(text)
            out.append({"image": image, "text": joined} if image else joined)
    return any_picture if check_only else out


async def _picture_embeddings(model: dict, body: dict):
    from ..knowledge.embed import NoPictures, embed

    items = _picture_items(body.get("input"))
    if not items:
        raise _err(400, "input is empty.")
    kind = "query" if body.get("input_type") == "query" else "document"
    try:
        vectors = await embed(model["id"], items, kind)
    except NoPictures as e:
        raise _err(400, str(e))
    except LoadError as e:
        raise _err(503, str(e), "model_load_failed")
    except RuntimeError as e:
        raise _err(502, str(e), "server_error")

    def encode(v):
        if body.get("encoding_format") == "base64":
            return base64.b64encode(v.astype("<f4").tobytes()).decode()
        return v.tolist()

    return {"object": "list", "model": model["id"],
            "data": [{"object": "embedding", "index": i, "embedding": encode(v)} for i, v in enumerate(vectors)],
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}
