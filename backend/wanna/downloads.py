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

from . import awake, db, hub
from .config import HOME, MODELS_DIR, MODELS_MARKER, disk_free, hf_token, models_dir
from .download_worker import download_files

log = logging.getLogger("wanna.downloads")
PENDING_FILE = HOME / "downloads.json"
_ctx = mp.get_context("spawn")


def _dir_size(path: Path, partials: bool = True) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            if not partials and name.endswith(".incomplete"):
                continue
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _clear_partials(path: Path) -> int:
    """Delete half-downloaded files left by a stopped download process, and return how many bytes that freed.

    huggingface_hub writes each file to a temporary name unique to the process and deletes it only when that process
    ends normally, so a partial from a killed or crashed process can never be resumed: it just takes up disk space
    and, as part of the folder's size, makes the download look further along than it is.
    """
    freed = 0
    for f in path.rglob("*.incomplete") if path.exists() else []:
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except OSError:
            pass
    return freed


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
        self.dest = models_dir() / self.model_id
        self._proc = None
        self.interrupted = False
        # Hugging Face's Xet downloader is fast but can hang for good at the same point of a file, so after a stall
        # the download carries on over plain HTTPS.
        self.xet = True

    def _make_model_id(self) -> str:
        base = _slug(self.repo_id.split("/")[-1].removesuffix("-GGUF").removesuffix("-gguf"))
        if self.details["engine"] in ("llamacpp", "sdcpp") and self.variant.get("quant"):
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
    # Dropped connections (Wi-Fi changing, the computer waking from sleep) are retried, waiting a little longer each
    # time: about a quarter of an hour in all before giving up.
    RETRY_WAITS = [5, 10, 20, 30] + [60] * 13

    def _spawn(self, q) -> None:
        self._proc = _ctx.Process(
            target=download_files, args=(self.repo_id, self.files, str(self.dest), hf_token(), q, self.xet),
            daemon=True,
        )
        self._proc.start()

    def run(self) -> None:
        self.status = "downloading"
        self.dest.mkdir(parents=True, exist_ok=True)
        awake.hold()  # a sleeping computer drops the connection
        try:
            result = self._download()
        finally:
            awake.let_go()
        if result is None:  # cancelled
            return

        if result[0] == "error":
            self.status = "error"
            self.error = _friendly_error(result[1])
            manager.save_pending()
            return
        shutil.rmtree(self.dest / ".cache", ignore_errors=True)
        for cache in (self.dest / "companions").glob("*/.cache"):
            shutil.rmtree(cache, ignore_errors=True)
        self.done_bytes = self.total
        self._register()
        self.status = "done"
        manager.save_pending()

    def _download(self) -> tuple[str, str | None] | None:
        """Download, retrying after dropped connections; finished files are reused each time."""
        for wait in [*self.RETRY_WAITS, None]:
            result = self._attempt()
            if result is None or result[0] == "done" or self.interrupted or wait is None or not _retryable(result[1]):
                return result
            log.warning("Download of %s failed (%s); trying again in %d s", self.repo_id, result[1], wait)
            self.speed = 0.0
            until = time.time() + wait
            while time.time() < until:
                if self.status == "cancelled":
                    return None
                time.sleep(0.5)

    def _attempt(self) -> tuple[str, str | None] | None:
        self._clear_partials()
        q = _ctx.Queue()
        self._spawn(q)
        last_bytes, last_t = _dir_size(self.dest), time.time()
        last_progress, restarts, last_loop = time.time(), 0, time.time()
        result = None
        while True:
            try:
                kind, payload = q.get(timeout=0.5)
                if kind in ("done", "error"):
                    result = (kind, payload)
                    break
                last_progress = time.time()  # bytes arrived, or a file finished
            except Exception:
                pass
            if self.status == "cancelled":
                return None
            if not self._proc.is_alive() and q.empty():
                # Killed from outside (usually wanna.sh shutting down): keep it queued for the next start.
                self.interrupted = True
                result = ("error", "Download process stopped unexpectedly.")
                break
            now = time.time()
            if now - last_loop > 10:
                # This loop runs twice a second, so a long gap means the computer was asleep: not a stall.
                last_progress = now
            last_loop = now
            size = _dir_size(self.dest)
            if size != self.done_bytes:
                last_progress = now
            if now - last_t >= 1.0:
                self.speed = max(0.0, (size - last_bytes) / (now - last_t))
                last_bytes, last_t = size, now
            self.done_bytes = size
            if now - last_progress > self.STALL_SECONDS:
                # A connection can hang without erroring. Restart; finished files are reused.
                self._proc.kill()
                self._proc.join(timeout=5)
                if restarts >= self.MAX_RESTARTS:
                    result = ("error", "Stalled: the download stopped making progress.")
                    break
                restarts += 1
                how = "over plain HTTPS instead of Xet" if self.xet else "over plain HTTPS"
                self.xet = False
                log.warning("Download of %s stalled; restarting %s (%d/%d)", self.repo_id, how, restarts,
                            self.MAX_RESTARTS)
                self._clear_partials()
                q = _ctx.Queue()
                self._spawn(q)
                last_progress = time.time()
        self._proc.join(timeout=5)
        if result[0] == "error":
            self._clear_partials()
        return result

    def _clear_partials(self) -> None:
        freed = _clear_partials(self.dest)
        if freed:
            size = f"{freed / 1e9:.1f} GB" if freed >= 1e9 else f"{freed / 1e6:.0f} MB"
            log.info("Deleted %s of unfinished files from an earlier try of %s", size, self.repo_id)
        self.done_bytes = _dir_size(self.dest)

    def _register(self) -> None:
        d, v = self.details, self.variant
        if d["engine"] == "sdcpp":
            from .download_worker import local_path

            parts = {k: local_path(ref) for k, ref in v["components"].items()}
            path = str(self.dest / parts["diffusion"])
            meta = {"quant": v.get("quant"), "edits": d.get("edits"), "makes": d.get("makes"),
                    "needs_image": bool(d.get("needs_image")),
                    # paths relative to the model's folder
                    "sdcpp": {"family": d.get("family"), "parts": parts},
                    "vram_bytes": v.get("weights"), "encoder_bytes": v.get("encoder_size")}
        elif d["engine"] == "llamacpp":
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


def _retryable(msg: str | None) -> bool:
    """Errors that trying again could fix: not a licence, a missing file, a full disk or a stall (already retried).

    The download process reports errors as "ExceptionType: message". A lost connection shows up as
    LocalEntryNotFoundError (nothing reachable, nothing cached), which is worth retrying; EntryNotFoundError isn't.
    """
    msg = msg or ""
    kind = msg.split(":", 1)[0]
    if kind in ("GatedRepoError", "RepositoryNotFoundError", "RemoteEntryNotFoundError", "EntryNotFoundError",
                "RevisionNotFoundError"):
        return False
    if kind == "HfHubHTTPError" and re.search(r"\b(401|403|404)\b", msg):
        return False
    return "No space left" not in msg and not msg.startswith("Stalled")


def _friendly_error(msg: str) -> str:
    if "GatedRepo" in msg or "401" in msg or "403" in msg:
        return ("This model needs you to accept its licence on huggingface.co and add your "
                "Hugging Face token in Settings → Accounts.")
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
        root = models_dir()
        try:
            root.mkdir(parents=True, exist_ok=True)
            if root != MODELS_DIR and not (root / MODELS_MARKER).exists():
                (root / MODELS_MARKER).write_text("wanna.sh saves models in this folder.\n")
        except OSError as e:
            raise ValueError(f"Can't save models to {root}: {e.strerror or e}. Check the drive is connected, or choose "
                             "another folder in Settings → Models & memory.")
        with self._lock:
            for d in self._downloads.values():
                if d.repo_id == repo_id and d.variant["id"] == variant["id"] and d.status in ("queued", "downloading"):
                    return d
            dl = Download(repo_id, variant, details)
            # Parts already downloaded (from an interrupted download) don't need the room again.
            # Unfinished files can't be resumed (see _clear_partials), so they don't count.
            missing = variant["size"] - (_dir_size(dl.dest, partials=False) if dl.dest.exists() else 0)
            free = disk_free(root)
            if missing > free:
                raise ValueError(
                    f"Not enough free space: this version needs {missing / 1e9:.0f} GB more and the drive models are "
                    f"saved to ({root}) has {free / 1e9:.0f} GB free. Free some space, choose a smaller version, "
                    "or save models to a bigger drive in Settings → Models & memory."
                )
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
