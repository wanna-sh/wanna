"""Code projects: a folder of files the agent works in, plus settings and conversation kept beside it."""

from __future__ import annotations

import io
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

from ..config import HOME

PROJECTS_DIR = HOME / "projects"  # the files the agent works on
META_DIR = HOME / "code"  # settings and conversation, kept out of the project folder
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

APPROVAL_MODES = ("ask_commands", "ask_all", "auto")
# Folders that are never interesting to list or search.
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build", ".cache", ".mypy_cache",
                ".pytest_cache", ".turbo", ".idea", ".vscode"}

_lock = threading.Lock()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return s or "project"


def _meta_path(pid: str) -> Path:
    return META_DIR / f"{pid}.json"


def valid_id(pid: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", pid)) and _meta_path(pid).exists()


def folder(pid: str) -> Path:
    return PROJECTS_DIR / pid


def create(name: str, description: str = "") -> dict:
    with _lock:
        base = _slug(name)
        pid, n = base, 2
        while _meta_path(pid).exists() or folder(pid).exists():
            pid, n = f"{base}-{n}", n + 1
        folder(pid).mkdir(parents=True)
        meta = {
            "id": pid,
            "name": name.strip() or pid,
            "description": description.strip(),
            "created": time.time(),
            "updated": time.time(),
            "approval": "ask_commands",
            "model": None,
            "context": None,  # None = automatic: the most that runs fully on the graphics cards
            "always_allow": [],  # exact commands the user said to always allow
        }
        _meta_path(pid).write_text(json.dumps(meta, indent=2))
    return meta


def get(pid: str) -> dict | None:
    try:
        return json.loads(_meta_path(pid).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save(meta: dict) -> dict:
    meta["updated"] = time.time()
    with _lock:
        _meta_path(meta["id"]).write_text(json.dumps(meta, indent=2))
    return meta


def update(pid: str, patch: dict) -> dict:
    meta = get(pid)
    if meta is None:
        raise KeyError(pid)
    for k in ("name", "description", "model"):
        if k in patch:
            meta[k] = patch[k]
    if patch.get("approval") in APPROVAL_MODES:
        meta["approval"] = patch["approval"]
    if "context" in patch:
        c = patch["context"]
        if c in (None, 0, "auto"):
            meta["context"] = None
        elif int(c) in (8192, 16384, 32768, 65536, 131072):
            meta["context"] = int(c)
    return save(meta)


def list_all() -> list[dict]:
    out = []
    for p in META_DIR.glob("*.json"):
        if p.name.endswith(".session.json"):
            continue
        m = get(p.stem)
        if m:
            m["files"] = sum(1 for _ in _walk(folder(m["id"])))
            out.append(m)
    return sorted(out, key=lambda m: -m["updated"])


def delete(pid: str) -> None:
    shutil.rmtree(folder(pid), ignore_errors=True)
    for p in (_meta_path(pid), META_DIR / f"{pid}.session.json"):
        p.unlink(missing_ok=True)


def _walk(root: Path):
    if not root.exists():
        return
    for p in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            yield p


def tree(pid: str, limit: int = 2000) -> list[dict]:
    """Files in the project (ignoring dependency folders), for the file browser."""
    root = folder(pid)
    files = []
    for p in _walk(root):
        try:
            st = p.stat()
        except OSError:
            continue
        files.append({"path": p.relative_to(root).as_posix(), "size": st.st_size, "modified": st.st_mtime})
        if len(files) >= limit:
            break
    return sorted(files, key=lambda f: f["path"])


def zip_bytes(pid: str) -> bytes:
    root = folder(pid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in _walk(root):
            z.write(p, f"{pid}/{p.relative_to(root).as_posix()}")
    return buf.getvalue()


# --- conversation -------------------------------------------------------------------------

def load_session(pid: str) -> dict:
    try:
        return json.loads((META_DIR / f"{pid}.session.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"messages": [], "events": [], "todos": []}


def save_session(pid: str, session: dict) -> None:
    (META_DIR / f"{pid}.session.json").write_text(json.dumps(session))
