"""Tiny SQLite store for installed models, generated media and API keys."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,            -- local id, e.g. "qwen3-4b-q4_k_m"
    repo_id TEXT NOT NULL,
    task TEXT NOT NULL,             -- chat | image | video | speech | transcribe | sound
    engine TEXT NOT NULL,           -- llamacpp | diffusers | transformers
    path TEXT NOT NULL,             -- directory, or the .gguf file for llamacpp
    files TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,             -- image | video | audio | text
    model_id TEXT,
    prompt TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    files TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn = _connect()
_conn.executescript(SCHEMA)
_conn.commit()


@contextmanager
def cursor():
    with _lock:
        cur = _conn.cursor()
        try:
            yield cur
            _conn.commit()
        finally:
            cur.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("files", "meta", "params"):
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


# models -------------------------------------------------------------------

def add_model(**m) -> dict:
    with cursor() as c:
        c.execute(
            "INSERT OR REPLACE INTO models (id, repo_id, task, engine, path, files, size_bytes, meta, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                m["id"], m["repo_id"], m["task"], m["engine"], m["path"],
                json.dumps(m.get("files", [])), m.get("size_bytes", 0),
                json.dumps(m.get("meta", {})), time.time(),
            ),
        )
    return get_model(m["id"])


def get_model(model_id: str) -> dict | None:
    with cursor() as c:
        return _row(c.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())


def list_models() -> list[dict]:
    with cursor() as c:
        return [_row(r) for r in c.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()]


def delete_model(model_id: str) -> None:
    with cursor() as c:
        c.execute("DELETE FROM models WHERE id=?", (model_id,))


# generations --------------------------------------------------------------

def add_generation(gen_id: str, kind: str, model_id: str | None, prompt: str, params: dict, files: list[str]) -> dict:
    with cursor() as c:
        c.execute(
            "INSERT INTO generations (id, kind, model_id, prompt, params, files, created_at) VALUES (?,?,?,?,?,?,?)",
            (gen_id, kind, model_id, prompt, json.dumps(params), json.dumps(files), time.time()),
        )
    return get_generation(gen_id)


def get_generation(gen_id: str) -> dict | None:
    with cursor() as c:
        return _row(c.execute("SELECT * FROM generations WHERE id=?", (gen_id,)).fetchone())


def list_generations(kind: str | None = None, limit: int = 100) -> list[dict]:
    with cursor() as c:
        if kind:
            rows = c.execute(
                "SELECT * FROM generations WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]


def delete_generation(gen_id: str) -> None:
    with cursor() as c:
        c.execute("DELETE FROM generations WHERE id=?", (gen_id,))


# api keys -----------------------------------------------------------------

def add_api_key(key_id: str, name: str, key_hash: str, prefix: str) -> None:
    with cursor() as c:
        c.execute(
            "INSERT INTO api_keys (id, name, key_hash, prefix, created_at) VALUES (?,?,?,?,?)",
            (key_id, name, key_hash, prefix, time.time()),
        )


def list_api_keys() -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT id, name, prefix, created_at, last_used_at FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def find_api_key(key_hash: str) -> dict | None:
    with cursor() as c:
        row = c.execute("SELECT * FROM api_keys WHERE key_hash=?", (key_hash,)).fetchone()
        if row:
            c.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (time.time(), row["id"]))
        return dict(row) if row else None


def delete_api_key(key_id: str) -> None:
    with cursor() as c:
        c.execute("DELETE FROM api_keys WHERE id=?", (key_id,))


def count_api_keys() -> int:
    with cursor() as c:
        return c.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
