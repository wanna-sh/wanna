"""OpenAI-compatible endpoints under /v1, so any OpenAI SDK or tool can point at wanna.sh."""

from __future__ import annotations

import base64
import json
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

from .. import db, jobs, presets
from ..config import OUTPUTS_DIR, UPLOADS_DIR
from ..workers.manager import LoadError, ModelNotFound, manager
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
    model = _resolve(body.get("model"), "chat")
    worker = await _ready(model)
    body["model"] = model["id"]

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
    job = await jobs.run_now("image", model, params, body["prompt"])
    return _image_payload(request, job, body.get("response_format"))


@router.post("/images/edits")
async def images_edits(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form(...),
    model: str | None = Form(None),
    n: int = Form(1),
    size: str | None = Form(None),
    response_format: str | None = Form(None),
    strength: float = Form(0.6),
    seed: int | None = Form(None),
):
    m = _resolve(model, "image")
    path = _save_upload(image)
    params = presets.apply(m, {"prompt": prompt, "n": n, "image": str(path), "strength": strength, "seed": seed})
    job = await jobs.run_now("image", m, params, prompt)
    return _image_payload(request, job, response_format)


def _save_upload(f: UploadFile) -> "Path":
    from pathlib import Path

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
    """Vectors for text from an installed search (embedding) model. Text is embedded exactly as sent."""
    body = await request.json()
    model = _resolve(body.get("model"), "embed")
    worker = await _ready(model)
    body["model"] = model["id"]
    return await _proxy(worker.url + "/v1/embeddings", body, worker.headers)
