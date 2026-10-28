"""API keys. Off by default; when enabled, every API call needs `Authorization: Bearer <key>`."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import HTTPException, Request

from .. import db
from ..config import load_settings

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(name: str) -> dict:
    key = "wanna-" + secrets.token_urlsafe(32)
    key_id = uuid.uuid4().hex[:12]
    db.add_api_key(key_id, name or "Untitled key", _hash(key), key[:12])
    return {"id": key_id, "name": name, "key": key, "prefix": key[:12]}


async def require_key(request: Request) -> None:
    if not load_settings().get("require_api_key"):
        return
    client = request.client.host if request.client else ""
    # The bundled UI on this machine never needs a key.
    if client in LOCAL_HOSTS and request.headers.get("x-wanna-ui") == "1":
        return
    auth = request.headers.get("authorization", "")
    key = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if not key or db.find_api_key(_hash(key)) is None:
        raise HTTPException(
            401,
            detail={"error": {"message": "Missing or invalid API key.", "type": "invalid_request_error",
                              "code": "invalid_api_key"}},
        )
