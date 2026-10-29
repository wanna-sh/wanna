"""Loads models into worker processes, places them on GPUs and routes requests to them."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import httpx

from .. import db, gpu
from ..config import HOME, LOGS_DIR, OUTPUTS_DIR, load_settings
from ..engines import llamacpp

log = logging.getLogger("wanna.manager")


PID_FILE = HOME / "workers.pid"


def _record_pids(pids: list[int]) -> None:
    # First line: the server that owns these workers.
    PID_FILE.write_text("\n".join(map(str, [os.getpid(), *pids])))


def _kill_orphans() -> None:
    """Stop workers left behind by a previous run that didn't shut down cleanly.

    Only when the server that started them is gone, so a second process importing wanna.sh
    (a script, a test) never stops a running server's models.
    """
    import psutil

    if not PID_FILE.exists():
        return
    lines = PID_FILE.read_text().split()
    if lines:
        try:
            owner = psutil.Process(int(lines[0]))
            if owner.is_running() and "wanna" in " ".join(owner.cmdline()) and owner.pid != os.getpid():
                return
        except (ValueError, psutil.Error):
            pass
    for line in lines[1:]:
        try:
            p = psutil.Process(int(line))
            cmd = " ".join(p.cmdline())
            if "llama-server" in cmd or "wanna.workers.runner" in cmd:
                log.info("Stopping leftover worker %s", line)
                p.kill()
        except (ValueError, psutil.Error):
            pass
    PID_FILE.unlink(missing_ok=True)


class ModelNotFound(Exception):
    pass


class LoadError(Exception):
    pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Worker:
    def __init__(self, model: dict, gpus: list[int], split, context: int | None, offload: bool):
        self.model = model
        self.id = model["id"]
        self.task = model["task"]
        self.engine = model["engine"]
        self.gpus = gpus
        self.split = split
        self.context = context
        self.offload = offload
        self.port = _free_port()
        self.status = "loading"  # loading | ready | error | stopped
        self.error: str | None = None
        self.started_at = time.time()
        self.last_used = time.time()
        self.proc: subprocess.Popen | None = None
        self.log_path = LOGS_DIR / f"{self.id}.log"
        self.ready = threading.Event()
        self.progress: dict = {}
        self.estimated_bytes = model.get("size_bytes", 0)
        self.plan: dict | None = None  # llama-fit-params result used for this load
        # The engine's port is on 127.0.0.1, but other programs and web pages (via DNS rebinding) could still reach it.
        # Every request to it carries this secret; only wanna.sh knows it.
        self.token = secrets.token_urlsafe(24)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self) -> None:
        if self.engine == "llamacpp":
            meta = self.model.get("meta") or {}
            cmd, env = llamacpp.server_command(
                self.model["path"], self.port, self.context or load_settings()["default_context"],
                self.gpus, self.split, mmproj=meta.get("mmproj"), alias=self.id,
                gpu_layers=(self.plan or {}).get("gpu_layers") if self.plan else None,
            )
            env["LLAMA_API_KEY"] = self.token  # via the environment, so it isn't visible in the process list
        else:
            meta = self.model.get("meta") or {}
            cmd = [
                sys.executable, "-m", "wanna.workers.runner",
                "--task", self.task, "--path", self.model["path"], "--port", str(self.port),
                "--outputs", str(OUTPUTS_DIR), "--gpu-count", str(len(self.gpus)),
            ]
            if meta.get("variant"):
                cmd += ["--variant", meta["variant"]]
            if self.offload:
                cmd.append("--offload")
            env = dict(os.environ)
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, self.gpus)) if self.gpus else ""
            env["WANNA_WORKER_TOKEN"] = self.token
            env["PYTHONUNBUFFERED"] = "1"
            env.setdefault("HF_HUB_OFFLINE", "1")
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get("PYTHONPATH", "")
        logf = open(self.log_path, "w")
        logf.write(" ".join(cmd) + "\n\n")
        logf.flush()
        kwargs = {"start_new_session": True} if os.name != "nt" else {}
        self.proc = subprocess.Popen(cmd, env=env, stdout=logf, stderr=subprocess.STDOUT, **kwargs)
        threading.Thread(target=self._wait_ready, daemon=True, name=f"wait-{self.id}").start()

    def _wait_ready(self) -> None:
        with httpx.Client(timeout=2) as c:
            while True:
                if self.proc.poll() is not None:
                    self.status = "error"
                    self.error = self.error or _tail_error(self.log_path)
                    self.ready.set()
                    return
                try:
                    r = c.get(f"{self.url}/health", headers=self.headers)
                    if r.status_code == 200:
                        body = r.json() if "json" in r.headers.get("content-type", "") else {}
                        st = body.get("status", "ok")
                        if st in ("ok", "ready"):
                            self.status = "ready"
                            self.ready.set()
                            return
                        if st == "error":
                            self.status, self.error = "error", body.get("error")
                            self.stop()
                            self.ready.set()
                            return
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(self.proc.pid, signal.SIGTERM)
                else:
                    self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    if os.name != "nt":
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    else:
                        self.proc.kill()
                except Exception:
                    pass
        if self.status != "error":
            self.status = "stopped"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "engine": self.engine,
            "status": self.status,
            "error": self.error,
            "gpus": self.gpus,
            "split": self.split,
            "offload": self.offload,
            "context": self.context,
            "gpu_layers": (self.plan or {}).get("gpu_layers"),
            "total_layers": (self.plan or {}).get("total_layers"),
            "started_at": self.started_at,
            "last_used": self.last_used,
            "title": (self.model.get("meta") or {}).get("title") or self.id,
        }


def _tail_error(path: Path) -> str:
    try:
        lines = path.read_text(errors="replace").strip().splitlines()
    except OSError:
        return "The model stopped unexpectedly."
    interesting = [l for l in lines if any(w in l.lower() for w in ("error", "out of memory", "exception", "failed"))]
    msg = (interesting[-1] if interesting else (lines[-1] if lines else "")).strip()
    if "out of memory" in msg.lower() or "outofmemory" in msg.lower():
        return "Not enough GPU memory for this model. Try a smaller version, or unload other models first."
    return msg[-400:] or "The model stopped unexpectedly."


class ModelManager:
    def __init__(self):
        self.workers: dict[str, Worker] = {}
        self._lock = threading.RLock()
        self.events: deque = deque(maxlen=50)
        _kill_orphans()
        threading.Thread(target=self._reaper, daemon=True, name="idle-reaper").start()
        threading.Thread(target=self._ram_guard, daemon=True, name="ram-guard").start()

    # --- queries ----------------------------------------------------------

    def loaded(self) -> list[dict]:
        return [w.to_dict() for w in self.workers.values() if w.status in ("loading", "ready")]

    def get(self, model_id: str) -> Worker | None:
        w = self.workers.get(model_id)
        return w if w and w.status in ("loading", "ready") else None

    def last_error(self, model_id: str) -> str | None:
        w = self.workers.get(model_id)
        return w.error if w and w.status == "error" else None

    def resolve(self, model: str | None, task: str) -> dict:
        """Find an installed model for a request. Accepts our id, a repo id, or nothing (auto)."""
        installed = [m for m in db.list_models() if m["task"] == task]
        if model and model not in ("auto", "default"):
            m = db.get_model(model)
            if m is None:
                m = next((x for x in installed if x["repo_id"].lower() == model.lower()), None)
            if m is None:
                m = next((x for x in installed if model.lower() in x["id"]), None)
            if m is None:
                raise ModelNotFound(f"Model '{model}' is not installed.")
            if m["task"] != task:
                raise ModelNotFound(f"Model '{m['id']}' is a {m['task']} model, not {task}.")
            return m
        for w in sorted(self.workers.values(), key=lambda w: -w.last_used):
            if w.task == task and w.status in ("loading", "ready"):
                return w.model
        if not installed:
            raise ModelNotFound(f"No {task} model installed yet. Download one from the Discover page.")
        return installed[0]

    # --- lifecycle --------------------------------------------------------

    def load(self, model_id: str, gpus: list[int] | None = None, context: int | None = None,
             offload: bool | None = None) -> Worker:
        model = db.get_model(model_id)
        if model is None:
            raise ModelNotFound(f"Model '{model_id}' is not installed.")
        with self._lock:
            existing = self.get(model_id)
            if existing:
                same = (gpus is None or sorted(gpus) == sorted(existing.gpus)) and (not context or context == existing.context)
                if same:
                    return existing
                self.unload(model_id)

            if model["engine"] == "llamacpp" and not llamacpp.installer.installed():
                llamacpp.installer.ensure()
                raise LoadError("The chat engine is still being set up. This happens once; please try again shortly.")

            need = self._estimate(model, context)
            if model["engine"] == "llamacpp" and gpus != []:
                planned = self._plan_llama(model, context or load_settings()["default_context"], gpus)
                if planned:
                    worker = Worker(model, planned["gpus"], planned["split"] if len(planned["gpus"]) > 1 else None,
                                    context, False)
                    worker.plan, worker.estimated_bytes = planned, need
                    self.workers[model_id] = worker
                    worker.start()
                    _record_pids([w.proc.pid for w in self.workers.values() if w.proc and w.proc.poll() is None])
                    spill = planned["total_layers"] - planned["gpu_layers"]
                    self._log(f"Loading {model_id} on {_gpu_label(planned['gpus'])}"
                              + (f" with {spill} of {planned['total_layers']} layers on the processor (slower)." if spill > 0 else "."))
                    return worker
            if gpus == []:
                plan = {"gpus": [], "split": None, "fits": True, "reason": "Running on the processor, as requested."}
            else:
                plan = gpu.plan_placement(need, gpus, self._reserved(), allow_split=True)
            if not plan["fits"] and not gpus:
                # Make room by unloading the least recently used models, then plan again.
                for w in sorted(self.workers.values(), key=lambda w: w.last_used):
                    if w.status in ("loading", "ready") and not w.progress.get("busy"):
                        self._log(f"Unloaded {w.id} to make room for {model_id}")
                        w.stop()
                        time.sleep(1.0)
                        plan = gpu.plan_placement(need, None, self._reserved(), allow_split=True)
                        if plan["fits"]:
                            break
            use_offload = offload if offload is not None else (not plan["fits"] and model["engine"] != "llamacpp")
            if use_offload and model["engine"] != "llamacpp":
                # Memory saver keeps every weight in system RAM. Refuse rather than let the OS kill things.
                import psutil

                weights = int((model.get("meta") or {}).get("vram_bytes") or model.get("size_bytes") or 0)
                free_ram = psutil.virtual_memory().available
                if weights * 1.15 > free_ram:
                    raise LoadError(
                        f"{(model.get('meta') or {}).get('title') or model_id} needs about "
                        f"{weights * 1.15 / 1e9:.0f} GB of graphics memory, or the same amount of free system "
                        f"memory to run in memory saver mode. This computer has {free_ram / 1e9:.0f} GB free. "
                        "Stop other models, close other programs, or choose a smaller model."
                    )
            if use_offload and not gpus and plan["gpus"]:
                # CPU offload streams one component at a time onto a single GPU: pick the roomiest one.
                roomiest = max(gpu.list_gpus(), key=lambda g: g["memory_free"])["index"]
                plan = {**plan, "gpus": [roomiest], "split": None,
                        "reason": f"Too big to keep fully on a GPU; streaming it through GPU {roomiest} (slower)."}
            worker = Worker(model, plan["gpus"], plan["split"], context, use_offload)
            worker.estimated_bytes = need
            self.workers[model_id] = worker
            worker.start()
            _record_pids([w.proc.pid for w in self.workers.values() if w.proc and w.proc.poll() is None])
            self._log(f"Loading {model_id} on {_gpu_label(plan['gpus'])}. {plan['reason']}")
            return worker

    def unload(self, model_id: str) -> None:
        with self._lock:
            w = self.workers.pop(model_id, None)
        if w:
            w.stop()
            self._log(f"Unloaded {model_id}")

    def unload_all(self) -> None:
        for mid in list(self.workers):
            self.unload(mid)

    async def ensure_ready(self, model: dict, timeout: float = 900) -> Worker:
        w = self.get(model["id"]) or await asyncio.to_thread(self.load, model["id"])
        ok = await asyncio.to_thread(w.ready.wait, timeout)
        if not ok:
            raise LoadError(f"{model['id']} took too long to load.")
        if w.status != "ready":
            raise LoadError(w.error or f"{model['id']} failed to load.")
        w.last_used = time.time()
        return w

    # --- internals --------------------------------------------------------

    def _plan_llama(self, model: dict, context: int, gpus: list[int] | None) -> dict | None:
        """Place a chat model with llama.cpp's own planner: one card if it fits fully (smallest first, keeping
        the others free), otherwise across the requested or all cards."""
        from .. import readiness

        if gpus:
            return readiness.fit_plan(model, context, gpus)
        cards = sorted(gpu.list_gpus(), key=lambda g: g["memory_free"])
        if not cards:
            return None
        if len(cards) > 1:
            for g in cards:
                p = readiness.fit_plan(model, context, [g["index"]])
                if p and p["full_gpu"]:
                    return p
        return readiness.fit_plan(model, context, sorted(g["index"] for g in cards))

    def _estimate(self, model: dict, context: int | None) -> int:
        size = int((model.get("meta") or {}).get("vram_bytes") or model.get("size_bytes") or 0)
        if model["engine"] == "llamacpp":
            ctx = context or load_settings()["default_context"]
            # KV cache is roughly proportional to context; ~0.11 MB/token for a 7B with GQA, scaled by model size.
            size += int(ctx * 0.11 * 1024**2 * max(0.3, size / (4.5 * 1024**3)))
        elif model["task"] in ("image", "video"):
            # Weights dominate; plan_placement adds headroom for activations on top of this.
            size = int(size * 1.05)
        return size

    def _reserved(self) -> dict[int, int]:
        """Memory promised to models still loading (NVML doesn't see it yet)."""
        out: dict[int, int] = {}
        for w in self.workers.values():
            if w.status == "loading" and w.gpus:
                share = w.estimated_bytes // len(w.gpus)
                for g in w.gpus:
                    out[g] = out.get(g, 0) + share
        return out

    def _log(self, msg: str) -> None:
        log.info(msg)
        self.events.appendleft({"time": time.time(), "message": msg})

    def _ram_guard(self) -> None:
        """Stop the hungriest worker before system RAM runs out.

        Left alone, the kernel's OOM killer may pick any process (or the whole WSL VM may be
        terminated), taking the user's other programs down with it.
        """
        import psutil

        floor = int(os.environ.get("WANNA_MIN_FREE_RAM_MB", "1200")) * 1024**2
        while True:
            time.sleep(1)
            if psutil.virtual_memory().available >= floor:
                continue
            victims = []
            for w in list(self.workers.values()):
                if w.proc and w.proc.poll() is None:
                    try:
                        victims.append((psutil.Process(w.proc.pid).memory_info().rss, w))
                    except psutil.Error:
                        pass
            if not victims:
                continue
            rss, w = max(victims, key=lambda v: v[0])
            log.warning("System memory almost exhausted; stopping %s (%.1f GB RSS)", w.id, rss / 1e9)
            w.error = ("Stopped because your computer ran out of system memory. Close other programs, "
                       "stop other models, or try a smaller model.")
            w.status = "error"
            w.stop()
            w.ready.set()
            self._log(f"Stopped {w.id}: computer ran out of memory")

    def _reaper(self) -> None:
        while True:
            time.sleep(30)
            minutes = load_settings().get("idle_unload_minutes") or 0
            for w in list(self.workers.values()):
                if w.status == "error" or (w.proc and w.proc.poll() is not None and w.status == "ready"):
                    if w.status == "ready":
                        w.status, w.error = "error", _tail_error(w.log_path)
                    continue
                if minutes and w.status == "ready" and time.time() - w.last_used > minutes * 60:
                    self._log(f"{w.id} was idle for {minutes} minutes")
                    self.unload(w.id)


def _gpu_label(gpus: list[int]) -> str:
    if not gpus:
        return "CPU"
    return "GPU " + " + ".join(map(str, gpus))


manager = ModelManager()
