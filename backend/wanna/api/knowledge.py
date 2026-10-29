"""Knowledge API under /api/knowledge: libraries of documents, and searching them (RAG)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import db, hub
from ..config import HOME
from ..downloads import manager as downloads
from ..knowledge import index, store
from ..knowledge.embed import NoSearchModel, default_model
from ..knowledge.search import context_prompt, search, words_only
from ..workers.manager import LoadError
from .auth import require_key

router = APIRouter(prefix="/api/knowledge", dependencies=[Depends(require_key)])

DEFAULT_SEARCH_MODEL = "Qwen/Qwen3-Embedding-0.6B-GGUF"
MAX_FILE = 100 * 1024 * 1024


def _library(lid: str) -> dict:
    lib = store.get_library(lid)
    if not lib:
        raise HTTPException(404, "Library not found")
    return lib


# --- search model ----------------------------------------------------------------------------------------

@router.get("/status")
def status():
    installed = [m for m in db.list_models() if m["task"] == "embed"]
    have = {m["repo_id"] for m in installed}
    active = [d for d in downloads.list() if d.get("task") == "embed" and d["status"] in ("queued", "downloading")]
    return {
        "search_models": [{"id": m["id"], "repo_id": m["repo_id"], "size_bytes": m["size_bytes"]} for m in installed],
        "default": (default_model() or {}).get("id"),
        "suggested": [{**c, "installed": c["repo_id"] in have} for c in hub.CURATED if c["task"] == "embed"],
        "downloading": active,
    }


class Setup(BaseModel):
    repo_id: str = DEFAULT_SEARCH_MODEL


@router.post("/setup")
def setup(req: Setup):
    """Download a search model (the recommended version)."""
    try:
        return downloads.start(req.repo_id, None).to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't start the download: {e}")


# --- libraries -------------------------------------------------------------------------------------------

class NewLibrary(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    hidden: bool = False  # a chat's own attachments


@router.get("/libraries")
def list_libraries(hidden: bool = False):
    return store.list_libraries(include_hidden=hidden)


@router.post("/libraries")
def create_library(req: NewLibrary):
    model = default_model()
    return store.create_library(req.name, req.description, model["id"] if model else None, req.hidden)


@router.get("/libraries/{lid}")
def get_library(lid: str):
    return {**_library(lid), "documents_list": store.list_documents(lid)}


class LibraryPatch(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/libraries/{lid}")
def update_library(lid: str, req: LibraryPatch):
    _library(lid)
    return store.update_library(lid, **req.model_dump(exclude_none=True))


@router.delete("/libraries/{lid}")
def delete_library(lid: str):
    _library(lid)
    store.delete_library(lid)
    return {"ok": True}


class Reindex(BaseModel):
    model: str


@router.post("/libraries/{lid}/reindex")
async def reindex(lid: str, req: Reindex):
    _library(lid)
    m = db.get_model(req.model)
    if not m or m["task"] != "embed":
        raise HTTPException(400, "That isn't an installed search model.")
    await index.reindex(lid, m["id"])
    return store.get_library(lid)


# --- documents -------------------------------------------------------------------------------------------

@router.get("/libraries/{lid}/documents")
def list_documents(lid: str):
    _library(lid)
    return store.list_documents(lid)


@router.post("/libraries/{lid}/documents")
async def add_documents(lid: str, files: list[UploadFile] = File(...)):
    _library(lid)
    added = []
    for f in files:
        data = await f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise HTTPException(413, f"{f.filename} is over 100 MB.")
        doc = store.add_document(lid, f.filename or "document", data)
        index.queue(doc["id"])
        added.append(doc)
    return added


@router.post("/documents/{did}/retry")
async def retry_document(did: str):  # async: indexing is queued on the server's event loop
    if not store.get_document(did):
        raise HTTPException(404, "Document not found")
    index.retry(did)
    return store.get_document(did)


@router.delete("/documents/{did}")
def delete_document(did: str):
    if not store.get_document(did):
        raise HTTPException(404, "Document not found")
    store.delete_document(did)
    return {"ok": True}


@router.get("/documents/{did}/file")
def document_file(did: str):
    doc = store.get_document(did)
    if not doc or not (HOME / doc["file"]).exists():
        raise HTTPException(404, "Document not found")
    return FileResponse(HOME / doc["file"], filename=doc["name"])


# --- search ----------------------------------------------------------------------------------------------

class Query(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    libraries: list[str] = Field(min_length=1)
    k: int = Field(default=6, ge=1, le=30)


async def _search(req: Query) -> list[dict]:
    for lid in req.libraries:
        _library(lid)
    try:
        return await search(req.query, req.libraries, req.k)
    except (NoSearchModel, LoadError) as e:
        raise HTTPException(503, str(e))


def _warnings(req: Query) -> list[str]:
    return [f'"{lib["name"]}" was read with a search model that has been removed, so it was only searched by exact '
            "words. Read it again on the Knowledge page to search it by meaning too." for lib in words_only(req.libraries)
            if not lib["hidden"]] + [
           "A long attachment in this chat was read with a search model that has been removed, so it was only searched "
           "by exact words." for lib in words_only(req.libraries) if lib["hidden"]][:1]


@router.post("/search")
async def search_libraries(req: Query):
    """The passages that best match a query, most relevant first."""
    return {"results": await _search(req), "warnings": _warnings(req)}


@router.post("/context")
async def chat_context(req: Query):
    """Search, then build the instructions and numbered passages to give a chat model (what Chat uses)."""
    results = await _search(req)
    return {"results": results, "prompt": context_prompt(results), "warnings": _warnings(req)}
