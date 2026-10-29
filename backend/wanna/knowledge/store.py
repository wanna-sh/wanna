"""Libraries, documents and passages in wanna.db. The original files are kept in <data folder>/knowledge/."""

from __future__ import annotations

import re
import shutil
import time
import uuid

from .. import db
from ..config import HOME

FILES_DIR = HOME / "knowledge"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "library"
    return f"{s}-{uuid.uuid4().hex[:6]}"


# --- libraries -------------------------------------------------------------------------------------------

def create_library(name: str, description: str = "", embed_model: str | None = None, hidden: bool = False) -> dict:
    lid, now = _slug(name), time.time()
    with db.cursor() as c:
        c.execute("INSERT INTO kb_libraries (id, name, description, embed_model, hidden, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?)", (lid, name.strip(), description.strip(), embed_model, int(hidden), now, now))
    return get_library(lid)


def get_library(lid: str) -> dict | None:
    with db.cursor() as c:
        row = c.execute(
            "SELECT l.*, (SELECT COUNT(*) FROM kb_documents d WHERE d.library_id = l.id) AS documents,"
            " (SELECT COUNT(*) FROM kb_chunks k WHERE k.library_id = l.id) AS passages,"
            " (SELECT COALESCE(SUM(size_bytes), 0) FROM kb_documents d WHERE d.library_id = l.id) AS size_bytes"
            " FROM kb_libraries l WHERE l.id = ?", (lid,)).fetchone()
    return _lib(dict(row)) if row else None


def list_libraries(include_hidden: bool = False) -> list[dict]:
    with db.cursor() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM kb_libraries WHERE hidden = 0 OR ? ORDER BY updated_at DESC",
                                       (int(include_hidden),)).fetchall()]
    return [get_library(i) for i in ids]


def _lib(d: dict) -> dict:
    d["hidden"] = bool(d["hidden"])
    return d


def update_library(lid: str, **fields) -> dict | None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "description", "embed_model")}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with db.cursor() as c:
            c.execute(f"UPDATE kb_libraries SET {sets}, updated_at = ? WHERE id = ?", (*allowed.values(), time.time(), lid))
    return get_library(lid)


def touch(lid: str) -> None:
    with db.cursor() as c:
        c.execute("UPDATE kb_libraries SET updated_at = ? WHERE id = ?", (time.time(), lid))


def delete_library(lid: str) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM kb_chunks WHERE library_id = ?", (lid,))
        c.execute("DELETE FROM kb_documents WHERE library_id = ?", (lid,))
        c.execute("DELETE FROM kb_libraries WHERE id = ?", (lid,))
    shutil.rmtree(FILES_DIR / lid, ignore_errors=True)


# --- documents -------------------------------------------------------------------------------------------

def add_document(lid: str, name: str, data: bytes) -> dict:
    did = uuid.uuid4().hex[:12]
    safe = re.sub(r"[^\w.\- ]+", "_", name).strip() or "document"
    folder = FILES_DIR / lid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{did}-{safe}"
    path.write_bytes(data)
    with db.cursor() as c:
        c.execute("INSERT INTO kb_documents (id, library_id, name, file, size_bytes, status, created_at)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (did, lid, name, path.relative_to(HOME).as_posix(), len(data), "queued", time.time()))
    touch(lid)
    return get_document(did)


def get_document(did: str) -> dict | None:
    with db.cursor() as c:
        row = c.execute("SELECT * FROM kb_documents WHERE id = ?", (did,)).fetchone()
    return dict(row) if row else None


def list_documents(lid: str) -> list[dict]:
    with db.cursor() as c:
        return [dict(r) for r in c.execute("SELECT * FROM kb_documents WHERE library_id = ? ORDER BY created_at DESC",
                                           (lid,)).fetchall()]


def documents_waiting() -> list[dict]:
    with db.cursor() as c:
        return [dict(r) for r in c.execute("SELECT * FROM kb_documents WHERE status IN ('queued', 'indexing')"
                                           " ORDER BY created_at").fetchall()]


def set_document(did: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db.cursor() as c:
        c.execute(f"UPDATE kb_documents SET {sets} WHERE id = ?", (*fields.values(), did))


def delete_document(did: str) -> None:
    doc = get_document(did)
    if not doc:
        return
    with db.cursor() as c:
        c.execute("DELETE FROM kb_chunks WHERE document_id = ?", (did,))
        c.execute("DELETE FROM kb_documents WHERE id = ?", (did,))
    (HOME / doc["file"]).unlink(missing_ok=True)
    touch(doc["library_id"])


# --- passages --------------------------------------------------------------------------------------------

def clear_vectors(lid: str) -> None:
    with db.cursor() as c:
        c.execute("UPDATE kb_chunks SET embedding = NULL WHERE library_id = ?", (lid,))
    touch(lid)


def replace_chunks(did: str, lid: str, chunks: list[dict], vectors) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM kb_chunks WHERE document_id = ?", (did,))
        c.executemany(
            "INSERT INTO kb_chunks (document_id, library_id, idx, page, heading, text, embedding) VALUES (?,?,?,?,?,?,?)",
            [(did, lid, i, ch["page"], ch["heading"], ch["text"], vectors[i].tobytes()) for i, ch in enumerate(chunks)])
    touch(lid)
