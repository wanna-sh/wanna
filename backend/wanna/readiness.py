"""Know before you run: what a model can do, what fits on this machine, how fast it is, and whether the
system is ready. Works for any hardware: one GPU, several, or none.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import httpx
import psutil

from . import gpu
from .config import DOCKER_NETWORK, LOGS_DIR, MODELS_DIR, load_settings
from .engines import llamacpp

log = logging.getLogger("wanna.readiness")

MEMORY_STEPS = (8192, 16384, 32768, 65536, 131072)
FIT_MARGIN_MB = 512  # free graphics memory to leave on each card when planning


# --- GGUF metadata (read from the file header; the weights are never loaded) ---------------------------------

_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_WANTED = re.compile(r"^(general\.architecture|general\.name|[\w.]+\.(context_length|block_count)|tokenizer\.chat_template)$")


@lru_cache(maxsize=64)
def gguf_info(path: str) -> dict:
    """Architecture, trained context length, layer count and chat template from a GGUF header."""
    out: dict = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path} isn't a GGUF file")
        version, _tensors, kv_count = struct.unpack("<IQQ", f.read(20))
        if version < 2:
            raise ValueError("GGUF version 1 isn't supported")

        def read_str() -> str:
            (n,) = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", errors="replace")

        def read_value(t: int, keep: bool):
            if t in _GGUF_SCALARS:
                fmt = _GGUF_SCALARS[t]
                return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
            if t == 8:
                if keep:
                    return read_str()
                (n,) = struct.unpack("<Q", f.read(8))
                f.seek(n, 1)
                return None
            if t == 9:  # array: skip it (token lists etc. are large and not needed)
                inner, n = struct.unpack("<IQ", f.read(12))
                if inner in _GGUF_SCALARS:
                    f.seek(struct.calcsize(_GGUF_SCALARS[inner]) * n, 1)
                else:
                    for _ in range(n):
                        read_value(inner, False)
                return None
            raise ValueError(f"unknown GGUF value type {t}")

        for _ in range(kv_count):
            key = read_str()
            (t,) = struct.unpack("<I", f.read(4))
            value = read_value(t, bool(_WANTED.match(key)))
            if _WANTED.match(key):
                out[key] = value
    arch = out.get("general.architecture", "")
    template = out.get("tokenizer.chat_template") or ""
    return {
        "architecture": arch,
        "name": out.get("general.name"),
        "context_length": out.get(f"{arch}.context_length"),
        "layers": out.get(f"{arch}.block_count"),
        # A template that mentions tools can format tool definitions and calls.
        "tools": bool(re.search(r"\btools\b", template)),
        # Reasoning models open a thinking block or expose a switch for it in their template.
        "thinks": bool(re.search(r"<think>|enable_thinking|reasoning_content|reasoning_effort", template)),
    }


def abilities(model: dict) -> dict:
    """What a chat model can do, from its file. Other kinds of model return {}."""
    if model.get("engine") != "llamacpp":
        return {}
    try:
        info = gguf_info(model["path"])
    except (OSError, ValueError) as e:
        log.warning("couldn't read %s: %s", model["path"], e)
        return {}
    return {
        "tools": info["tools"],
        "thinks": info["thinks"],
        "vision": bool((model.get("meta") or {}).get("mmproj")),
        "trained_context": info["context_length"],
        "layers": info["layers"],
    }


# --- memory planning with llama.cpp's own fitter ----------------------------------------------------------------

_plan_cache: dict[tuple, dict] = {}
_plan_lock = threading.Lock()


def fit_plan(model: dict, context: int, gpus: list[int] | None = None) -> dict | None:
    """Ask llama.cpp how this model loads at this context on these GPUs (None = all), using free memory now.

    Returns {"context", "gpu_layers", "total_layers", "full_gpu", "split"} or None if it couldn't plan.
    """
    if not llamacpp.installer.installed() or model.get("engine") != "llamacpp":
        return None
    visible = gpus if gpus is not None else [g["index"] for g in gpu.list_gpus()]
    # Free memory changes as models load; plans are reused for a short while only.
    key = (model["path"], context, tuple(visible), int(time.time() // 30))
    with _plan_lock:
        if key in _plan_cache:
            return _plan_cache[key]
    exe = installer_dir() / ("llama-fit-params.exe" if os.name == "nt" else "llama-fit-params")
    if not exe.exists():
        return None
    cmd = [str(exe), "-m", model["path"], "-c", str(context)]
    mmproj = (model.get("meta") or {}).get("mmproj")
    if visible:
        # Free memory to leave on each card. llama.cpp's default of 1 GB per card proved too cautious (on a
        # 3070 + 3060 it halved Qwen 27B's speed while 3 GB sat unused), so leave 512 MB. The fitter can't
        # take a vision projector, so its size is reserved on the first card, where llama.cpp loads it.
        try:
            extra = int(Path(mmproj).stat().st_size / 1024**2) if mmproj else 0
        except OSError:
            extra = 0
        margins = [FIT_MARGIN_MB + extra] + [FIT_MARGIN_MB] * (len(visible) - 1)
        cmd += ["--fit-target", ",".join(map(str, margins))]
    env = dict(os.environ, LD_LIBRARY_PATH=str(installer_dir()) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""),
               CUDA_DEVICE_ORDER="PCI_BUS_ID", CUDA_VISIBLE_DEVICES=",".join(map(str, visible)))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    args = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    ngl = re.search(r"-ngl (-?\d+)", args)
    ts = re.search(r"-ts ([\d,]+)", args)
    if not ngl:
        return None
    try:
        layers = (gguf_info(model["path"])["layers"] or 0) + 1  # +1 for the output layer, as llama.cpp counts
    except (OSError, ValueError):
        layers = 0
    # -1 means every layer fits on the graphics cards.
    gl = layers if int(ngl.group(1)) < 0 else int(ngl.group(1))
    plan = {
        "context": context,
        "gpu_layers": gl,
        "total_layers": layers,
        "full_gpu": bool(visible) and layers > 0 and gl >= layers,
        "split": [float(x) for x in ts.group(1).split(",")] if ts else None,
        "gpus": visible,
    }
    with _plan_lock:
        _plan_cache[key] = plan
    # A plan made while no model is loaded reflects the whole machine; keep it on the model for later.
    if not _loaded_elsewhere(None):
        from . import db

        saved = (model.get("meta") or {}).get("memory_plans", {})
        saved[f"{context}:{','.join(map(str, visible))}"] = plan
        db.update_model_meta(model["id"], {"memory_plans": saved})
    return plan


def installer_dir() -> Path:
    return llamacpp.installer.dir


def memory_options(model: dict, gpus: list[int] | None = None) -> dict:
    """Every sensible memory size for this model on this machine, rated, plus a recommendation."""
    ab = abilities(model)
    trained = ab.get("trained_context") or 131072
    steps = [c for c in MEMORY_STEPS if c <= trained] or [min(MEMORY_STEPS)]
    visible = gpus if gpus is not None else [g["index"] for g in gpu.list_gpus()]
    saved = (model.get("meta") or {}).get("memory_plans", {})
    busy = _loaded_elsewhere(None)

    def plan_for(c: int):
        clean = saved.get(f"{c}:{','.join(map(str, visible))}")
        # While anything is loaded, live plans are pessimistic, so a saved clean plan is better.
        return clean if (busy and clean) else fit_plan(model, c, gpus)

    with ThreadPoolExecutor(len(steps)) as ex:
        plans = list(ex.map(plan_for, steps))
    options = []
    for c, p in zip(steps, plans):
        if p is None:
            options.append({"context": c, "rating": "unknown", "label": "Can't check on this computer"})
            continue
        if not p["gpus"]:
            rating, label = "slow", "Runs on the processor"
        elif p["full_gpu"]:
            rating, label = "fast", "Fast: fits fully on your graphics cards"
        elif p["gpu_layers"] >= p["total_layers"] * 0.75:
            rating, label = "ok", f"A little slower: {p['total_layers'] - p['gpu_layers']} of {p['total_layers']} layers on the processor"
        else:
            rating, label = "slow", f"Slow: {p['total_layers'] - p['gpu_layers']} of {p['total_layers']} layers on the processor"
        options.append({"context": c, "rating": rating, "label": label, "plan": p})
    fast = [o["context"] for o in options if o["rating"] == "fast"]
    recommended = max(fast) if fast else min(steps)
    return {"options": options, "recommended": recommended, "trained_context": ab.get("trained_context"),
            # Live plans made while these were loaded see less free memory than this machine really has.
            "measured_with_loaded": busy}


def recommended_context(model: dict, floor: int = 8192, cap: int = 65536) -> int:
    """The biggest memory that keeps the model fully on the graphics cards (within sensible bounds)."""
    try:
        rec = memory_options(model)["recommended"]
    except Exception:
        return 16384
    return max(floor, min(cap, rec))


def _loaded_elsewhere(model_id: str | None) -> list[str]:
    """Models currently holding graphics memory (other than model_id)."""
    from .workers.manager import manager

    return [w["id"] for w in manager.loaded() if w["id"] != model_id]


# --- measured speed ------------------------------------------------------------------------------------------------

_SPEED = re.compile(r"eval time =\s+[\d.]+ ms /\s+(\d+) tokens \(\s*[\d.]+ ms per token,\s+([\d.]+) tokens per second\)")


def measured_speed(model_id: str) -> float | None:
    """Tokens per second from the model's most recent long-enough reply on this machine."""
    p = LOGS_DIR / f"{model_id}.log"
    try:
        with open(p, "rb") as f:
            f.seek(max(0, p.stat().st_size - 200_000))
            tail = f.read().decode(errors="replace")
    except OSError:
        return None
    # Skip the prompt-eval lines and very short replies, which give noisy figures.
    rates = [float(m.group(2)) for m in _SPEED.finditer(tail) if int(m.group(1)) >= 32]
    return round(rates[-1], 1) if rates else None


# --- system check ------------------------------------------------------------------------------------------------------

_check_cache: tuple[float, list] | None = None
_torch_cache: dict | None = None


def _torch_status() -> dict:
    """Whether the Python AI libraries are installed and can use a GPU (checked in a subprocess: importing torch is slow)."""
    global _torch_cache
    if _torch_cache is not None:
        return _torch_cache
    if importlib.util.find_spec("torch") is None:
        _torch_cache = {"installed": False}
        return _torch_cache
    code = "import torch, json; print(json.dumps({'cuda': torch.cuda.is_available(), 'version': torch.__version__, " \
           "'mps': getattr(torch.backends, 'mps', None) is not None and torch.backends.mps.is_available()}))"
    try:
        import json
        import sys

        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        _torch_cache = {"installed": True, **json.loads(r.stdout.strip().splitlines()[-1])}
    except Exception:
        _torch_cache = {"installed": True, "cuda": False}
    return _torch_cache


def system_check(refresh: bool = False) -> list[dict]:
    global _check_cache
    if _check_cache and not refresh and time.time() - _check_cache[0] < 60:
        return _check_cache[1]
    checks: list[dict] = []

    def add(cid, label, status, detail):
        checks.append({"id": cid, "label": label, "status": status, "detail": detail})

    gpus = gpu.list_gpus()
    drv = gpu.cuda_driver_version()
    if gpus:
        names = ", ".join(f"{g['name'].removeprefix('NVIDIA ').removeprefix('GeForce ')} ({g['memory_total'] / 1024**3:.0f} GB)" for g in gpus)
        add("gpu", "Graphics cards", "ok", f"{names}. CUDA driver {drv[0]}.{drv[1]}." if drv else names)
    else:
        add("gpu", "Graphics cards", "warn", "No NVIDIA graphics card found. Chat and Code run on the processor, so pick "
            "small models. Pictures, video, voices and music need an NVIDIA card in this version.")

    st = llamacpp.installer.state()
    if llamacpp.installer.installed():
        add("engine", "Chat engine", "ok", f"llama.cpp {st['version']}, {st['backend']}.")
    elif st["status"] == "installing":
        add("engine", "Chat engine", "warn", f"Setting up ({round(st['progress'] * 100)}%). This happens once.")
    else:
        add("engine", "Chat engine", "fail" if st["status"] == "error" else "warn",
            st.get("error") or "Not set up yet. It installs itself the first time you chat.")

    t = _torch_status()
    if not t.get("installed"):
        from . import addons

        ok, reason = addons.can_install()
        add("python", "Pictures, video, voices and music", "warn",
            "Not installed yet. Open Pictures, Videos, Read aloud, Transcribe or Music to add them (a one-time download, "
            "about 3 GB)." if ok else reason)
    elif t.get("cuda"):
        add("python", "Pictures, video, voices and music", "ok", f"PyTorch {t.get('version')} with GPU support.")
    else:
        add("python", "Pictures, video, voices and music", "warn",
            f"PyTorch {t.get('version', '')} can't see a graphics card, so these run on the processor and are very slow."
            + (" This Mac's GPU isn't supported yet." if t.get("mps") else ""))

    from .code import sandbox

    code_off_in_docker = bool(os.environ.get("WANNA_IN_DOCKER")) and not DOCKER_NETWORK
    if code_off_in_docker:
        add("docker", "Code sandbox", "warn", "Code is off because wanna.sh runs in Docker. To turn it on, see "
            "\"Turning on Code\" in the Docker guide; it gives wanna.sh access to Docker on your computer.")
    else:
        ds = sandbox.docker_status()
        add("docker", "Code sandbox", "ok" if ds["docker"] and ds["image"] else ("warn" if ds["docker"] else "fail"),
            f"Docker {ds.get('version')}, sandbox ready." if ds["docker"] and ds["image"] else ds["message"])

    free = shutil.disk_usage(MODELS_DIR).free
    add("disk", "Free disk space", "ok" if free > 50e9 else ("warn" if free > 10e9 else "fail"),
        f"{free / 1e9:.0f} GB free for models." + ("" if free > 50e9 else " Big models need 5 to 30 GB each."))

    ram = psutil.virtual_memory()
    add("ram", "System memory", "ok" if ram.total > 15e9 else "warn",
        f"{ram.total / 1024**3:.0f} GB, {ram.available / 1024**3:.0f} GB free now."
        + ("" if ram.total > 15e9 else " Large models may be slow or fail to load."))

    try:
        r = httpx.head("https://huggingface.co", timeout=8, follow_redirects=True)
        add("hf", "Hugging Face", "ok" if r.status_code < 500 else "warn", "Reachable, so models can be found and downloaded.")
    except httpx.HTTPError:
        add("hf", "Hugging Face", "warn", "Can't reach huggingface.co. Installed models still work; finding new ones needs internet.")

    from .code import search

    if code_off_in_docker:
        add("search", "Web search for Code", "warn", "Off, along with Code.")
    elif (load_settings().get("brave_api_key") or "").strip():
        add("search", "Web search for Code", "ok", "Brave Search, using your API key, with local SearXNG as backup.")
    else:
        sx = search.searxng_state()
        last = search.status
        if sx == "no-docker":
            add("search", "Web search for Code", "warn", "Local search needs Docker. Until then searches fall back to "
                "DuckDuckGo, which blocks after bursts of searches. Or add a Brave Search key below.")
        elif last["error"] and not last["ok_at"]:
            add("search", "Web search for Code", "warn", f"Last search failed: {last['error'][:160]}")
        elif sx == "running":
            add("search", "Web search for Code", "ok", "SearXNG is running privately on this computer.")
        else:
            add("search", "Web search for Code", "ok", "SearXNG starts on the first search (the first time it "
                "downloads about 100 MB).")

    _check_cache = (time.time(), checks)
    return checks
