"""Index documents in the background: extract text, split it into passages, embed them, store them."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import HOME
from ..workers.manager import LoadError
from . import chunk, store
from .embed import NoSearchModel, default_model, embed
from .extract import ExtractError, extract

log = logging.getLogger("wanna.knowledge")

MAX_CHARS = 5_000_000  # per document, about a million words
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
            parts, pages, truncated = await asyncio.to_thread(extract, data, doc["name"], MAX_CHARS)
            passages = await asyncio.to_thread(chunk.chunks, parts, doc["name"])
            if not passages:
                raise ExtractError("There's no text in this document to search.")
            # The document's name and section go in front of each passage, so they count when matching.
            texts = [f"{doc['name']}{' > ' + p['heading'] if p['heading'] else ''}\n{p['text']}" for p in passages]
            vectors = []
            step = 128
            for i in range(0, len(texts), step):
                if store.get_document(did) is None:
                    return  # deleted while indexing
                vectors.append(await embed(model_id, texts[i:i + step], "document"))
                store.set_document(did, progress=min(len(texts), i + step) / len(texts))
            import numpy as np

            await asyncio.to_thread(store.replace_chunks, did, lib["id"], passages, np.vstack(vectors))
            store.set_document(did, status="ready", progress=1, chunks=len(passages), pages=pages,
                               truncated=int(truncated))
            log.info("indexed %s: %d passages", doc["name"], len(passages))
        except (ExtractError, NoSearchModel, LoadError) as e:
            store.set_document(did, status="error", error=str(e))
        except (RuntimeError, httpx.HTTPError, OSError) as e:
            log.exception("indexing %s failed", doc["name"])
            store.set_document(did, status="error", error=f"Indexing failed: {e}")


async def reindex(lid: str, model_id: str) -> None:
    """Embed every document in a library again, with another search model."""
    store.update_library(lid, embed_model=model_id)
    for doc in store.list_documents(lid):
        store.set_document(doc["id"], status="queued", progress=0, error=None)
        queue(doc["id"])
