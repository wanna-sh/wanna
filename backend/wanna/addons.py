"""Add-ons installed on demand: the AI libraries for pictures, video, voices and music ("ml").

Installs that start with chat only (the desktop app, `install.sh --chat-only`) download these the first time someone
needs them, into wanna.sh's own Python environment, using uv.

PyTorch comes from PyTorch's own package index, matched to the graphics driver (uv's --torch-backend): on Windows the
normal index only has a processor-only build, and on Linux its CUDA build may be newer than the driver supports.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import gpu

log = logging.getLogger("wanna.addons")

# PyTorch CUDA builds, newest first: (CUDA version, uv torch backend). Checked on download.pytorch.org on 2026-10-29:
# cu132 has PyTorch 2.15.0, cu130 and cu126 have 2.14.1, for Windows and Linux.
TORCH_CUDA_BACKENDS = [((13, 2), "cu132"), ((13, 0), "cu130"), ((12, 6), "cu126")]

state = {"status": "idle", "message": "", "error": None, "downloaded": 0, "to_download": 0, "log": []}
_lock = threading.Lock()


def ml_installed() -> bool:
    importlib.invalidate_caches()
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("diffusers") is not None


def _uv() -> str | None:
    """uv: given by the desktop app (WANNA_UV), on PATH, or where install.sh puts it."""
    for candidate in (os.environ.get("WANNA_UV"), shutil.which("uv"), str(Path.home() / ".local" / "bin" / "uv")):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def can_install() -> tuple[bool, str | None]:
    if sys.platform == "darwin" and platform.machine() != "arm64":
        return False, "PyTorch, which these need, isn't made for Macs with an Intel processor any more."
    if os.environ.get("WANNA_IN_DOCKER"):
        return False, "In Docker, use the full image (ghcr.io/wanna-sh/wanna:latest) for pictures, video, voices and music."
    if sys.prefix == sys.base_prefix:
        return False, "wanna.sh isn't running in its own Python environment, so it won't install packages into it."
    if not os.access(sys.prefix, os.W_OK):
        return False, f"wanna.sh can't write to its Python environment ({sys.prefix})."
    if _uv() is None:
        return False, "uv isn't installed, which wanna.sh uses to install them. Run the installer again."
    return True, None


def torch_backend() -> tuple[str | None, str]:
    """(uv --torch-backend value, or None for the normal index; description) for this computer."""
    if sys.platform == "darwin":
        return None, "PyTorch for Mac"
    drv = gpu.cuda_driver_version() if gpu.list_gpus() else None
    if drv:
        for cuda, name in TORCH_CUDA_BACKENDS:
            if tuple(drv) >= cuda:
                return name, f"PyTorch with CUDA {cuda[0]}.{cuda[1]}"
    return "cpu", "PyTorch for the processor (no supported NVIDIA graphics card found)"


def ml_requirements() -> list[str]:
    """The [ml] extra's requirements, read from wanna.sh's own package metadata."""
    reqs = importlib.metadata.requires("wanna") or []
    return [r.split(";")[0].strip() for r in reqs if re.search(r"""extra\s*==\s*["']ml["']""", r)]


def download_size() -> str:
    # Measured from the packages' sizes: PyTorch with CUDA is most of it; PyTorch for Mac is far smaller.
    return "about 300 MB" if sys.platform == "darwin" else "about 3 GB"


def status() -> dict:
    ok, reason = can_install()
    return {"ml": {"installed": ml_installed(), "can_install": ok, "reason": reason, "size": download_size(),
                   **{k: v for k, v in state.items() if k != "log"}, "log": state["log"][-5:]}}


def install_ml() -> None:
    """Start installing in the background (once)."""
    ok, reason = can_install()
    if not ok:
        raise RuntimeError(reason)
    with _lock:
        if state["status"] == "installing":
            return
        state.update(status="installing", message="Getting ready", error=None, downloaded=0, to_download=0, log=[])
    threading.Thread(target=_install_ml, daemon=True, name="install-ml").start()


def _install_ml() -> None:
    backend, what = torch_backend()
    cmd = [_uv(), "pip", "install", "--python", sys.executable, *ml_requirements()]
    if backend:
        # PyTorch's packages from its index for this driver; everything else from the normal one.
        cmd += ["--torch-backend", backend]
    log.info("Installing the AI libraries (%s): %s", what, " ".join(cmd))
    state["message"] = f"Downloading {what}"
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                env={**os.environ, "UV_NO_PROGRESS": "1"}, **kwargs)
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            state["log"] = (state["log"] + [line])[-50:]
            # uv prints "Downloading torch (2.4GiB)" when it starts each large download and "Downloaded torch" after.
            if line.startswith("Downloading "):
                state["to_download"] += 1
                state["message"] = f"{line} ({what})"
            elif line.startswith("Downloaded "):
                state["downloaded"] += 1
            elif line.startswith(("Prepared", "Installed", "Uninstalled")):
                state["message"] = line
        code = proc.wait()
        if code != 0:
            raise RuntimeError("\n".join(state["log"][-5:]) or f"uv exited with {code}")
        from . import readiness

        readiness._torch_cache = None  # the system check looks again
        state.update(status="done", message="Installed", error=None)
        log.info("AI libraries installed")
    except (OSError, RuntimeError) as e:
        log.error("Installing the AI libraries failed: %s", e)
        state.update(status="error", error=str(e)[-600:], message="Install failed")
