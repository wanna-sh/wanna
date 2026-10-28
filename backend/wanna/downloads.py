"""Download manager.

Each download runs in its own process so it can be cancelled instantly. Progress is
measured by watching bytes land on disk, which works for both plain HTTP and Xet transfers.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import db, hub
from .config import HOME, MODELS_DIR, hf_token
from .download_worker import download_files

log = logging.getLogger("wanna.downloads")
PENDING_FILE = HOME / "downloads.json"
_ctx = mp.get_context("spawn")


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


_DTYPE_BYTES = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8, "I32": 4, "I16": 2, "I8": 1, "U8": 1,
                "F8_E4M3": 1, "F8_E5M2": 1, "BOOL": 1}


def _half_precision_bytes(root: Path) -> int:
    """Size the weights will take in GPU memory at 16-bit, read from safetensors headers (no tensor data loaded)."""
    import json
    import struct

    total = 0
    for f in root.rglob("*.safetensors"):
        try:
            with open(f, "rb") as fh:
                n = struct.unpack("<Q", fh.read(8))[0]
                header = json.loads(fh.read(n))
        except Exception:
            continue
        for name, t in header.items():
            if name == "__metadata__":
                continue
            numel = 1
            for d in t["shape"]:
                numel *= d
            # Anything stored wider than 16 bits gets loaded at 16 bits; 8-bit stays 8-bit.
            total += numel * min(2, _DTYPE_BYTES.get(t["dtype"], 2))
    return total


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


class Download:
    def __init__(self, repo_id: str, variant: dict, details: dict):
        self.id = uuid.uuid4().hex[:12]
        self.repo_id = repo_id
        self.variant = variant
        self.details = details
        self.files: list[str] = variant["files"]
        self.total = variant["size"]
        self.done_bytes = 0
        self.speed = 0.0
        self.status = "queued"  # queued | downloading | done | error | cancelled
        self.error: str | None = None
        self.started_at = time.time()
        self.model_id = self._make_model_id()
        self.dest = MODELS_DIR / self.model_id
        self._proc = None
        self.interrupted = False

    def _make_model_id(self) -> str:
        base = _slug(self.repo_id.split("/")[-1].removesuffix("-GGUF").removesuffix("-gguf"))
        if self.details["engine"] == "llamacpp" and self.variant.get("quant"):
            base = f"{base}-{_slug(self.variant['quant'])}"
        return base

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "model_id": self.model_id,
            "title": self.details.get("title"),
            "task": self.details.get("task"),
            "variant": self.variant.get("label"),
            "total": self.total,
            "done": min(self.done_bytes, self.total) if self.total else self.done_bytes,
            "progress": (min(1.0, self.done_bytes / self.total) if self.total else 0.0),
            "speed": self.speed,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
        }

    STALL_SECONDS = 90
    MAX_RESTARTS = 3

    def _spawn(self, q) -> None:
        self._proc = _ctx.Process(
            target=download_files, args=(self.repo_id, self.files, str(self.dest), hf_token(), q), daemon=True
        )
        self._proc.start()

    def run(self) -> None:
        self.status = "downloading"
        self.dest.mkdir(parents=True, exist_ok=True)
        q = _ctx.Queue()
        self._spawn(q)
        last_bytes, last_t = _dir_size(self.dest), time.time()
        last_progress, restarts = time.time(), 0
        result = None
        while True:
            try:
                kind, payload = q.get(timeout=0.5)
                if kind in ("done", "error"):
                    result = (kind, payload)
                    break
                last_progress = time.time()  # a file finished
            except Exception:
                pass
            if self.status == "cancelled":
                return
            if not self._proc.is_alive() and q.empty():
                # Killed from outside (usually wanna.sh shutting down): keep it queued for the next start.
                self.interrupted = True
                result = ("error", "Download process stopped unexpectedly.")
                break
            now = time.time()
            size = _dir_size(self.dest)
            if size != self.done_bytes:
                last_progress = now
            if now - last_t >= 1.0:
                self.speed = max(0.0, (size - last_bytes) / (now - last_t))
                last_bytes, last_t = size, now
            self.done_bytes = size
            if now - last_progress > self.STALL_SECONDS:
                # A connection can hang without erroring. Restart; finished files and partials are reused.
                self._proc.kill()
                self._proc.join(timeout=5)
                if restarts >= self.MAX_RESTARTS:
                    result = ("error", "Stalled: the download stopped making progress.")
                    break
                restarts += 1
                log.warning("Download of %s stalled; restarting (%d/%d)", self.repo_id, restarts, self.MAX_RESTARTS)
                q = _ctx.Queue()
                self._spawn(q)
                last_progress = time.time()
        self._proc.join(timeout=5)

        if result[0] == "error":
            self.status = "error"
            self.error = _friendly_error(result[1])
            manager.save_pending()
            return
        shutil.rmtree(self.dest / ".cache", ignore_errors=True)
        self.done_bytes = self.total
        self._register()
        self.status = "done"
        manager.save_pending()

    def _register(self) -> None:
        d, v = self.details, self.variant
        if d["engine"] == "llamacpp":
            weights = [f for f in self.files if "mmproj" not in f.lower()]
            projector = next((f for f in self.files if "mmproj" in f.lower()), None)
            path = str(self.dest / sorted(weights)[0])
            meta = {"quant": v.get("quant"), "mmproj": str(self.dest / projector) if projector else None}
        else:
            path = str(self.dest)
            meta = {"variant": v.get("variant"), "pipeline_tag": d.get("pipeline_tag"),
                    "needs_image": bool(d.get("needs_image")),
                    "vram_bytes": _half_precision_bytes(self.dest) or None}
        meta["title"] = d.get("title")
        db.add_model(
            id=self.model_id, repo_id=self.repo_id, task=d["task"], engine=d["engine"], path=path,
            files=self.files, size_bytes=self.total, meta=meta,
        )

    def cancel(self) -> None:
        self.status = "cancelled"
        if self._proc and self._proc.is_alive():
            self._proc.kill()
        shutil.rmtree(self.dest, ignore_errors=True)


def _friendly_error(msg: str) -> str:
    if "GatedRepo" in msg or "401" in msg or "403" in msg:
        return ("This model needs you to accept its licence on huggingface.co and add your "
                "Hugging Face token in Settings.")
    if msg.startswith("Stalled"):
        return "The download kept stalling. Check your internet connection and try again."
    if "No space left" in msg:
        return "Your disk is full. Free some space and try again."
    if "ConnectError" in msg or "ConnectionError" in msg or "Timeout" in msg:
        return "Couldn't reach Hugging Face. Check your internet connection."
    return msg


class DownloadManager:
    def __init__(self):
        self._downloads: dict[str, Download] = {}
        self._lock = threading.Lock()

    def save_pending(self) -> None:
        """Remember unfinished downloads so they resume after a restart."""
        import json

        pending = [{"repo_id": d.repo_id, "variant_id": d.variant["id"]}
                   for d in self._downloads.values()
                   if d.status in ("queued", "downloading") or (d.status == "error" and d.interrupted)]
        PENDING_FILE.write_text(json.dumps(pending))

    def resume_pending(self) -> None:
        """Restart downloads that were unfinished when wanna.sh last stopped. Called once at server start."""
        threading.Thread(target=self._resume, daemon=True, name="resume-downloads").start()

    def _resume(self) -> None:
        import json

        try:
            pending = json.loads(PENDING_FILE.read_text()) if PENDING_FILE.exists() else []
        except json.JSONDecodeError:
            pending = []
        for p in pending:
            try:
                log.info("Resuming download of %s", p["repo_id"])
                self.start(p["repo_id"], p["variant_id"])
            except Exception as e:
                log.warning("Couldn't resume %s: %s", p["repo_id"], e)

    def start(self, repo_id: str, variant_id: str | None = None) -> Download:
        details = hub.details(repo_id)
        if not details["supported"]:
            raise ValueError("wanna.sh can't run this kind of model yet.")
        variants = details["variants"]
        if not variants:
            raise ValueError("No downloadable files found for this model.")
        variant = next((v for v in variants if v["id"] == variant_id), None) if variant_id else None
        if variant is None:
            variant = next(v for v in variants if v["id"] == details["recommended"])
        with self._lock:
            for d in self._downloads.values():
                if d.repo_id == repo_id and d.variant["id"] == variant["id"] and d.status in ("queued", "downloading"):
                    return d
            dl = Download(repo_id, variant, details)
            self._downloads[dl.id] = dl
        threading.Thread(target=dl.run, daemon=True, name=f"download-{dl.id}").start()
        self.save_pending()
        return dl

    def list(self) -> list[dict]:
        return [d.to_dict() for d in sorted(self._downloads.values(), key=lambda d: -d.started_at)]

    def get(self, dl_id: str) -> Download | None:
        return self._downloads.get(dl_id)

    def cancel(self, dl_id: str) -> None:
        d = self._downloads.get(dl_id)
        if d and d.status in ("queued", "downloading"):
            d.cancel()
            self.save_pending()

    def clear_finished(self) -> None:
        with self._lock:
            for k in [k for k, d in self._downloads.items() if d.status in ("done", "error", "cancelled")]:
                del self._downloads[k]


manager = DownloadManager()
