"""Native API under /api: model hub, downloads, model management, generation jobs, gallery, settings."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import catalog, db, gpu, hub, jobs, presets, readiness, samplers
from ..config import MODELS_DIR, OUTPUTS_DIR, UPLOADS_DIR, load_settings, save_settings
from ..downloads import manager as downloads
from ..engines import llamacpp
from ..workers.manager import LoadError, ModelNotFound, manager
from .auth import create_key, require_key

router = APIRouter(prefix="/api", dependencies=[Depends(require_key)])

UPLOAD_ID = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]{1,8}$")


# --- system -----------------------------------------------------------------

@router.get("/system")
def system():
    info = gpu.system_info()
    loaded = manager.loaded()
    for g in info["gpus"]:
        g["models"] = [w["id"] for w in loaded if g["index"] in w["gpus"]]
    info["engines"] = {"llamacpp": llamacpp.installer.state()}
    info["loaded"] = loaded
    info["events"] = list(manager.events)[:20]
    info["disk_free"] = shutil.disk_usage(MODELS_DIR).free
    info["tasks"] = hub.TASKS
    return info


@router.get("/system/check")
def system_check(refresh: bool = False):
    """Is this computer ready? One line per area, each ok / warn / fail."""
    return readiness.system_check(refresh)


@router.post("/engines/llamacpp/install")
def install_llamacpp():
    llamacpp.installer.ensure()
    return llamacpp.installer.state()


# --- hub --------------------------------------------------------------------

SORTS = ("popular", "trending", "newest", "liked")


@router.get("/hub/browse")
def hub_browse(task: str, q: str = "", sort: str = "popular", fits: bool = True, limit: int = 24, offset: int = 0):
    """Runnable models for one task, rated for this computer."""
    if task not in hub.TASKS or sort not in SORTS:
        raise HTTPException(400, "Unknown task or sort order")
    try:
        out = catalog.browse(task, q.strip(), sort, fits, min(limit, 60), max(0, offset))
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach Hugging Face: {e}")
    _mark_installed(out["results"])
    return out


@router.get("/hub/overview")
def hub_overview(q: str = "", per_task: int = 4):
    """The best few models per task for this computer."""
    out = catalog.overview(q.strip(), min(per_task, 12))
    for s in out["sections"]:
        _mark_installed(s["results"])
    return out


def _mark_installed(items: list[dict]) -> None:
    installed = {m["repo_id"] for m in db.list_models()}
    for it in items:
        it["installed"] = it["repo_id"] in installed


@router.get("/hub/model/{repo_id:path}")
def hub_model(repo_id: str):
    try:
        d = hub.details(repo_id)
    except Exception as e:
        raise HTTPException(404, f"Couldn't load this model from Hugging Face: {e}")
    d["installed"] = [m["id"] for m in db.list_models() if m["repo_id"] == repo_id]
    return d


# --- downloads --------------------------------------------------------------

class DownloadReq(BaseModel):
    repo_id: str
    variant_id: str | None = None


@router.post("/downloads")
def start_download(req: DownloadReq):
    try:
        return downloads.start(req.repo_id, req.variant_id).to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't start the download: {e}")


@router.get("/downloads")
def list_downloads():
    return downloads.list()


@router.delete("/downloads/{dl_id}")
def cancel_download(dl_id: str):
    downloads.cancel(dl_id)
    return {"ok": True}


@router.post("/downloads/clear")
def clear_downloads():
    downloads.clear_finished()
    return {"ok": True}


# --- installed models -------------------------------------------------------

@router.get("/models")
def list_models():
    workers = {w["id"]: w for w in manager.loaded()}
    out = []
    for m in db.list_models():
        m["loaded"] = workers.get(m["id"])
        m["last_error"] = manager.last_error(m["id"])
        m["task_label"] = hub.TASKS.get(m["task"], {}).get("label")
        m["defaults"] = presets.for_model(m)
        if m["engine"] == "llamacpp":
            m["abilities"] = readiness.abilities(m)
            m["speed"] = readiness.measured_speed(m["id"])
        if m["task"] == "image":
            m["samplers"] = samplers.options_for(m["repo_id"], m["path"])
        out.append(m)
    return out


class LoadReq(BaseModel):
    gpus: list[int] | None = None
    context: int | None = None
    offload: bool | None = None


@router.post("/models/{model_id}/load")
def load_model(model_id: str, req: LoadReq):
    try:
        # None = automatic placement, [] = processor only, [i, ...] = those GPUs.
        return manager.load(model_id, req.gpus, req.context, req.offload).to_dict()
    except ModelNotFound as e:
        raise HTTPException(404, str(e))
    except LoadError as e:
        raise HTTPException(409, str(e))


@router.post("/models/{model_id}/unload")
def unload_model(model_id: str):
    manager.unload(model_id)
    return {"ok": True}


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    m = db.get_model(model_id)
    if not m:
        raise HTTPException(404, "Not installed")
    manager.unload(model_id)
    target = (MODELS_DIR / model_id).resolve()
    if target.is_relative_to(MODELS_DIR.resolve()) and target != MODELS_DIR.resolve():
        shutil.rmtree(target, ignore_errors=True)
    db.delete_model(model_id)
    return {"ok": True}


@router.get("/models/{model_id}/memory")
def model_memory(model_id: str):
    """How each conversation-memory size would run on this computer, with a recommendation."""
    m = db.get_model(model_id)
    if not m or m["engine"] != "llamacpp":
        raise HTTPException(404, "Only chat models have memory options")
    return readiness.memory_options(m)


@router.get("/models/{model_id}/log", response_class=PlainTextResponse)
def model_log(model_id: str):
    from ..config import LOGS_DIR

    p = LOGS_DIR / f"{model_id}.log"
    if not p.exists() or not p.resolve().is_relative_to(LOGS_DIR.resolve()):
        return ""
    return p.read_text(errors="replace")[-20000:]


# --- generation jobs ----------------------------------------------------------

@router.post("/uploads")
def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()[:8] or ".bin"
    if not re.fullmatch(r"\.[a-z0-9]{1,7}", ext):
        ext = ".bin"
    name = f"{uuid.uuid4().hex}{ext}"
    with open(UPLOADS_DIR / name, "wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"id": name, "filename": file.filename}


# Text pulled from a document is capped so one huge file can't swamp memory or the browser.
EXTRACT_MAX_CHARS = 400_000


@router.post("/extract-text")
def extract_text(file: UploadFile = File(...)):
    """Text from a PDF or plain-text file, for attaching documents to a chat."""
    name = (file.filename or "").lower()
    data = file.file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "That file is over 50 MB. Try a smaller document.")
    pages = None
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        import io

        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise HTTPException(400, "This PDF is password protected. Unlock it and attach it again.")
            parts, total = [], 0
            for page in reader.pages:
                t = page.extract_text() or ""
                parts.append(t)
                total += len(t)
                if total > EXTRACT_MAX_CHARS:
                    break
            text, pages = "\n\n".join(parts), len(reader.pages)
        except PdfReadError as e:
            raise HTTPException(400, f"Couldn't read this PDF: {e}")
        if not text.strip():
            raise HTTPException(
                400, "This PDF has no selectable text (it may be scanned pictures of pages), so there's nothing to read."
            )
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        if "\x00" in text[:4096]:
            raise HTTPException(400, "This doesn't look like a text document. Attach a PDF, text, Markdown, CSV or code file.")
    truncated = len(text) > EXTRACT_MAX_CHARS
    return {"text": text[:EXTRACT_MAX_CHARS], "pages": pages, "chars": min(len(text), EXTRACT_MAX_CHARS), "truncated": truncated}


def _upload_path(upload_id: str | None) -> str | None:
    if not upload_id:
        return None
    if not UPLOAD_ID.match(upload_id) or not (UPLOADS_DIR / upload_id).exists():
        raise HTTPException(400, "Unknown upload")
    return str(UPLOADS_DIR / upload_id)


@router.post("/generate/{task}")
async def generate(task: str, params: dict):
    if task not in ("image", "video", "speech", "sound", "transcribe"):
        raise HTTPException(400, "Unknown task")
    try:
        model = manager.resolve(params.pop("model", None), task)
    except ModelNotFound as e:
        raise HTTPException(404, str(e))
    # Never accept raw file paths from clients; only ids from /api/uploads.
    image = _upload_path(params.pop("image_upload", None))
    audio = _upload_path(params.pop("file_upload", None))
    params.pop("image", None)
    params.pop("file", None)
    if image:
        params["image"] = image
    if audio:
        params["file"] = audio
    if task == "transcribe" and not audio:
        raise HTTPException(400, "Attach an audio file first")
    if task in ("image", "video"):
        params = presets.apply(model, params)
    prompt = params.get("prompt") or params.get("text") or ""
    return jobs.submit(task, model, params, prompt).to_dict()


@router.get("/jobs")
def list_jobs():
    return jobs.recent()


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j.to_dict()


# --- gallery ----------------------------------------------------------------

@router.get("/gallery")
def gallery(kind: str | None = None, limit: int = 200):
    return db.list_generations(kind, limit)


@router.delete("/gallery/{gen_id}")
def delete_generation(gen_id: str):
    g = db.get_generation(gen_id)
    if g:
        for f in g["files"]:
            p = (OUTPUTS_DIR / f).resolve()
            if p.is_relative_to(OUTPUTS_DIR.resolve()):
                p.unlink(missing_ok=True)
        db.delete_generation(gen_id)
    return {"ok": True}


# --- settings & keys --------------------------------------------------------

def _public_settings(s: dict) -> dict:
    s = dict(s)
    tok = s.get("hf_token") or ""
    s["hf_token"] = (tok[:6] + "…" + tok[-4:]) if tok else ""
    s["hf_token_set"] = bool(tok)
    return s


@router.get("/settings")
def get_settings():
    return _public_settings(load_settings())


@router.put("/settings")
def put_settings(patch: dict):
    if "hf_token" in patch and "…" in (patch["hf_token"] or ""):
        patch.pop("hf_token")  # unchanged masked value
    s = save_settings(patch)
    hub._model_info.cache_clear()
    return _public_settings(s)


class KeyReq(BaseModel):
    name: str = ""


@router.get("/keys")
def list_keys():
    return db.list_api_keys()


@router.post("/keys")
def new_key(req: KeyReq):
    return create_key(req.name)


@router.delete("/keys/{key_id}")
def delete_key(key_id: str):
    db.delete_api_key(key_id)
    return {"ok": True}
