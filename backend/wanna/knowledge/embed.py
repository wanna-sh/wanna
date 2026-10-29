"""Turn text into vectors with the installed search (embedding) model, which runs on llama.cpp like chat models."""

from __future__ import annotations

import time

import httpx
import numpy as np

from .. import db
from ..workers.manager import manager
from .families import family

BATCH = 32  # passages per request


class NoSearchModel(Exception):
    pass


def default_model() -> dict | None:
    """The search model new libraries use: the most recently installed one."""
    models = [m for m in db.list_models() if m["task"] == "embed"]
    return models[0] if models else None


async def embed(model_id: str, texts: list[str], kind: str) -> np.ndarray:
    """Normalised float32 vectors, one row per text. kind is "query" or "document"."""
    model = db.get_model(model_id)
    if model is None:
        raise NoSearchModel(f"The search model '{model_id}' isn't installed any more. Install it again, or re-index "
                            "the library with another search model.")
    prefix = family(model["repo_id"])[kind]
    worker = await manager.ensure_ready(model)
    worker.last_used = time.time()
    rows: list[list[float]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10), headers=worker.headers) as c:
        for i in range(0, len(texts), BATCH):
            batch = [prefix + t for t in texts[i:i + BATCH]]
            r = await c.post(f"{worker.url}/v1/embeddings", json={"input": batch, "model": model_id})
            if r.status_code != 200:
                raise RuntimeError(f"The search model returned an error: {r.text[:300]}")
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            rows += [d["embedding"] for d in data]
    v = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)
