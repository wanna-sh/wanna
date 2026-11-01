"""Index documents in the background: extract text, split it into passages, embed them, store them."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .. import db
from ..config import HOME
from ..workers.manager import LoadError
from . import chunk, pictures, store
from .embed import NoPictures, NoSearchModel, default_model, embed, picture
from .extract import ExtractError, extract, page_pictures
from .families import sees_pictures
from .pictures import PictureError, is_picture

log = logging.getLogger("wanna.knowledge")

MAX_CHARS = 5_000_000  # per document, about a million words
PICTURE_STEP = 8  # pictures embedded between progress updates
_lock = asyncio.Lock()  # one document at a time: the search model is shared, and order is predictable
_tasks: set[asyncio.Task] = set()
_loop: asyncio.AbstractEventLoop | None = None  # the server's loop, for searches started from worker threads


def loop() -> asyncio.AbstractEventLoop | None:
    return _loop


def queue(did: str) -> None:
    """Index a document soon. Safe to call from request handlers."""
    t = asyncio.get_running_loop().create_task(_index(did))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def resume() -> None:
    """Pick up documents that were waiting when wanna.sh last stopped. Called once at startup, on the server's loop."""
    global _loop
    _loop = asyncio.get_running_loop()
    for doc in store.documents_waiting():
        store.set_document(doc["id"], status="queued", progress=0)
        queue(doc["id"])


async def _index(did: str) -> None:
    async with _lock:
        doc = store.get_document(did)
        lib = store.get_library(doc["library_id"]) if doc else None
        if not doc or not lib:
            return  # deleted while waiting
        model_id = lib["embed_model"]
        if not model_id:
            m = default_model()
            if m is None:
                store.set_document(did, status="error", error="Install a search model first (Knowledge page).")
                return
            model_id = m["id"]
            store.update_library(lib["id"], embed_model=model_id)
        store.set_document(did, status="indexing", progress=0, error=None)
        try:
            data = await asyncio.to_thread((HOME / doc["file"]).read_bytes)
            model = db.get_model(model_id)
            sees = bool(model) and sees_pictures(model)
            passages, items, pages, truncated = await asyncio.to_thread(_read, doc, data, sees)
            vectors = []
            step = PICTURE_STEP if any(isinstance(i, dict) for i in items) else 128
            for i in range(0, len(items), step):
                if store.get_document(did) is None:
                    return  # deleted while indexing
                vectors.append(await embed(model_id, items[i:i + step], "document"))
                store.set_document(did, progress=min(len(items), i + step) / len(items))
            import numpy as np

            await asyncio.to_thread(store.replace_chunks, did, lib["id"], passages, np.vstack(vectors))
            store.set_document(did, status="ready", progress=1, chunks=len(passages), pages=pages,
                               truncated=int(truncated))
            log.info("indexed %s: %d passages", doc["name"], len(passages))
        except (ExtractError, NoSearchModel, NoPictures, LoadError) as e:
            store.set_document(did, status="error", error=str(e))
        except (RuntimeError, httpx.HTTPError, OSError) as e:
            log.exception("indexing %s failed", doc["name"])
            store.set_document(did, status="error", error=f"Indexing failed: {e}")


def _read(doc: dict, data: bytes, sees: bool) -> tuple[list[dict], list, int | None, bool]:
    """(passages, what to embed for each, page count, truncated). A picture is one passage, embedded as the picture.
    With a search model that can see pictures, the pages of a PDF that have no text (scans, photos) are passages too,
    one picture each."""
    name = doc["name"]
    if is_picture(data, name):
        if not sees:
            raise ExtractError("This is a picture. To search pictures, read this library with a search model that can "
                               "see them, such as Qwen3 VL Embedding.")
        try:
            return [{"page": None, "heading": "", "text": f"Picture: {name}", "picture": doc["file"]}], \
                [picture(data)], None, False
        except PictureError as e:
            raise ExtractError(str(e))
    parts, pages, truncated = extract(data, name, MAX_CHARS, pictures_ok=sees)
    passages = chunk.chunks(parts, name)
    # The document's name and section go in front of each passage, so they count when matching.
    items: list = [f"{name}{' > ' + p['heading'] if p['heading'] else ''}\n{p['text']}" for p in passages]
    blank = [page for page, text in parts if page and not text.strip()]
    if sees and blank:
        for page, image in page_pictures(data, blank):
            kind = pictures.kind(image)
            path = store.page_pictures_dir(doc) / f"{doc['id']}-page-{page}.{'jpg' if kind == 'jpeg' else kind}"
            path.write_bytes(image)
            passages.append({"page": page, "heading": "", "text": f"Picture of page {page} of {name}",
                             "picture": path.relative_to(HOME).as_posix()})
            items.append(picture(image))
    if not passages:
        raise ExtractError("There's no text in this document to search."
                           + (" Its pages are pictures, but none of them could be read." if blank else ""))
    return passages, items, pages, truncated


def retry(did: str) -> None:
    """Try a document that failed again, for example after installing a search model."""
    store.set_document(did, status="queued", progress=0, error=None)
    queue(did)


async def reindex(lid: str, model_id: str) -> None:
    """Read every document in a library again, with this search model (and the current way of splitting text).

    The old vectors are dropped first: two models' vectors can't be compared. Word search keeps working on the old
    passages until each document is done.
    """
    store.clear_vectors(lid)
    store.update_library(lid, embed_model=model_id)
    for doc in store.list_documents(lid):
        store.set_document(doc["id"], status="queued", progress=0, error=None)
        queue(doc["id"])
