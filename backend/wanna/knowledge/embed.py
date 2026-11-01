"""Turn text (and pictures, for models that can see them) into vectors with the installed search (embedding) model,
which runs on llama.cpp like chat models."""

from __future__ import annotations

import base64
import time

import httpx
import numpy as np

from .. import db
from ..workers.manager import manager
from .families import chat_prompt, family, sees_pictures
from .pictures import readable

BATCH = 32  # passages per request
PICTURE_BATCH = 4  # pictures take far more of the model's memory than text
_markers: dict[str, str] = {}  # one run of a model -> its media marker (llama.cpp makes a new one each start)


class NoSearchModel(Exception):
    pass


class NoPictures(Exception):
    """The search model reads text only."""


def default_model() -> dict | None:
    """The search model new libraries use: the most recently installed one."""
    models = [m for m in db.list_models() if m["task"] == "embed"]
    return models[0] if models else None


def picture(data: bytes) -> dict:
    """An item for embed(): a picture, given as its file's bytes."""
    return {"image": base64.b64encode(readable(data)).decode()}


async def embed(model_id: str, items: list[str | dict], kind: str) -> np.ndarray:
    """Normalised float32 vectors, one row per item. kind is "query" or "document". An item is text, or for a model
    that can see pictures, {"image": base64} with optional "text" (see picture())."""
    model = db.get_model(model_id)
    if model is None:
        raise NoSearchModel(f"The search model {model_id} isn't installed. Install it again, or read the library again "
                            "with another search model on the Knowledge page.")
    spec = family(model["repo_id"])
    pictures = sees_pictures(model)
    if not pictures and any(isinstance(i, dict) and i.get("image") for i in items):
        raise NoPictures(f"{(model.get('meta') or {}).get('title') or model_id} reads text only, so it can't search "
                         "pictures. Use a search model that can, such as Qwen3 VL Embedding.")
    worker = await manager.ensure_ready(model)
    worker.last_used = time.time()
    rows: list[list[float]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10), headers=worker.headers) as c:
        marker = await _marker(c, worker.url, worker.token) if pictures else None

        def payload(item: str | dict):
            text, image = (item, None) if isinstance(item, str) else (item.get("text") or "", item.get("image"))
            if not pictures:
                return spec[kind] + text
            prompt = chat_prompt(spec[kind], text, marker if image else None)
            return {"prompt_string": prompt, "multimodal_data": [image]} if image else prompt

        size = PICTURE_BATCH if pictures and any(isinstance(i, dict) for i in items) else BATCH
        for i in range(0, len(items), size):
            batch = [payload(it) for it in items[i:i + size]]
            r = await c.post(f"{worker.url}/v1/embeddings", json={"input": batch, "model": model_id})
            if r.status_code != 200:
                raise RuntimeError(f"The search model returned an error: {r.text[:300]}")
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            rows += [d["embedding"] for d in data]
    v = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)


async def _marker(c: httpx.AsyncClient, url: str, run: str) -> str:
    """Where a picture goes in a prompt: llama.cpp's media marker for this run of the model."""
    if run not in _markers:
        r = await c.get(f"{url}/props")
        r.raise_for_status()
        _markers[run] = r.json()["media_marker"]
    return _markers[run]
