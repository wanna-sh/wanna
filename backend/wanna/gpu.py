"""GPU discovery and placement.

Uses NVML (nvidia-ml-py). Machines without NVIDIA GPUs fall back to CPU.
"""

from __future__ import annotations

import logging
import os
import threading

import psutil

log = logging.getLogger("wanna.gpu")

try:
    import pynvml

    pynvml.nvmlInit()
    _NVML = True
except Exception:  # no driver, no NVIDIA GPU, or library missing
    _NVML = False

_lock = threading.Lock()


def cuda_driver_version() -> tuple[int, int] | None:
    if not _NVML:
        return None
    v = pynvml.nvmlSystemGetCudaDriverVersion()  # e.g. 13030
    return v // 1000, (v % 1000) // 10


def list_gpus() -> list[dict]:
    """Return one dict per GPU, indexed the same way as CUDA_VISIBLE_DEVICES."""
    if not _NVML:
        return []
    gpus = []
    with _lock:
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
            except pynvml.NVMLError:
                util = None
            try:
                temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            except pynvml.NVMLError:
                temp = None
            name = pynvml.nvmlDeviceGetName(h)
            gpus.append(
                {
                    "index": i,
                    "name": name.decode() if isinstance(name, bytes) else name,
                    "uuid": _str(pynvml.nvmlDeviceGetUUID(h)),
                    "memory_total": int(mem.total),
                    "memory_used": int(mem.used),
                    "memory_free": int(mem.free),
                    "utilization": util,
                    "temperature": temp,
                }
            )
    # Keep CUDA's ordering consistent with NVML's (PCI bus order).
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    return gpus


def _str(v) -> str:
    return v.decode() if isinstance(v, bytes) else v


def system_info() -> dict:
    vm = psutil.virtual_memory()
    return {
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_total": int(vm.total),
        "ram_available": int(vm.available),
        "cuda_driver": ".".join(map(str, cuda_driver_version())) if cuda_driver_version() else None,
        "gpus": list_gpus(),
    }


def plan_placement(
    required_bytes: int,
    requested: list[int] | None = None,
    reserved: dict[int, int] | None = None,
    allow_split: bool = True,
) -> dict:
    """Decide which GPU(s) a model should run on.

    requested: explicit GPU indices from the user (None or [] means "auto").
    reserved: bytes already promised to models that are still loading, per GPU.
    Returns {"gpus": [...], "split": [...fractions] | None, "fits": bool, "reason": str}.
    """
    gpus = list_gpus()
    if not gpus:
        return {"gpus": [], "split": None, "fits": True, "reason": "No GPU found, running on CPU."}

    reserved = reserved or {}
    free = {g["index"]: max(0, g["memory_free"] - reserved.get(g["index"], 0)) for g in gpus}
    # Leave some headroom for the CUDA context and activations.
    need = int(required_bytes * 1.15) + 512 * 1024**2

    if requested:
        chosen = [i for i in requested if i in free]
        if not chosen:
            return {"gpus": [], "split": None, "fits": False, "reason": "Selected GPU(s) not found."}
        total = sum(free[i] for i in chosen)
        split = _split_by_free(chosen, free) if len(chosen) > 1 else None
        return {
            "gpus": chosen,
            "split": split,
            "fits": total >= need,
            "reason": "Using the GPU(s) you picked." if total >= need else "Might not fit in the selected GPU memory.",
        }

    # Auto: smallest single GPU that fits (keeps the big ones free), else split across the biggest.
    by_free = sorted(free.items(), key=lambda kv: kv[1])
    for idx, f in by_free:
        if f >= need:
            return {"gpus": [idx], "split": None, "fits": True, "reason": f"Fits on GPU {idx}."}

    if allow_split and len(gpus) > 1:
        chosen, total = [], 0
        for idx, f in sorted(free.items(), key=lambda kv: kv[1], reverse=True):
            chosen.append(idx)
            total += f
            if total >= need:
                break
        chosen.sort()
        return {
            "gpus": chosen,
            "split": _split_by_free(chosen, free),
            "fits": total >= need,
            "reason": f"Split across GPUs {', '.join(map(str, chosen))}."
            if total >= need
            else "Too big for your GPUs; part of it will run on the CPU (slower).",
        }

    best = by_free[-1][0]
    return {"gpus": [best], "split": None, "fits": False, "reason": "Too big for your GPU; part of it will run on the CPU (slower)."}


def _split_by_free(indices: list[int], free: dict[int, int]) -> list[float]:
    total = sum(free[i] for i in indices) or 1
    return [round(free[i] / total, 3) for i in indices]
