"""stable-diffusion.cpp engine: installs the library for this machine. Picture models in GGUF and single-file formats
(Qwen-Image and its editing models, and others) run on it, loaded into wanna.sh's own worker process through the
library's C interface (see workers/sdcpp_lib.py). Nothing of it listens on a port.

Releases ship ready-made builds for Windows (CUDA, Vulkan, CPU) and macOS, but for Linux only CPU, Vulkan and ROCm. On
Linux with an NVIDIA card it's built from source with CUDA when the tools to build it are there (CUDA toolkit, cmake,
git and a C++ compiler); otherwise the ready-made build is used, and it's built again once the tools appear.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import zipfile
from pathlib import Path

import httpx

from .. import gpu
from ..config import ENGINES_DIR

log = logging.getLogger("wanna.sdcpp")

# Pinned, tested release and its commit (for building from source). Override both to try a newer one.
DEFAULT_TAG = os.environ.get("WANNA_SDCPP_TAG", "master-1043-3be2378")
COMMIT = os.environ.get("WANNA_SDCPP_COMMIT", "3be23788fc0c9f35a2c24b1211caae11d4a54dbc")
REPO = "leejet/stable-diffusion.cpp"
ROOT = ENGINES_DIR / "sdcpp"
LIB = {"Windows": "stable-diffusion.dll", "Darwin": "libstable-diffusion.dylib"}.get(platform.system(),
                                                                                    "libstable-diffusion.so")
# Marker for a build made without the graphics card because the tools to build for it were missing.
NO_GPU_TOOLS = "no CUDA build tools"
# The Mac release is built for macOS 26 and newer (its library's minimum version, read from the file on 2026-11-03).
MAC_MIN = 26
MAC_TOO_OLD = (f"GGUF picture models need macOS {MAC_MIN} or newer on a Mac: the picture engine they run on "
               "(stable-diffusion.cpp) is only built for it. Other picture models work as usual.")
# Step-by-step instructions for installing those tools.
GPU_HELP_URL = "https://wanna.sh/docs/guides/linux-gpu-pictures/"


class Installer:
    """Downloads (or builds) the right stable-diffusion.cpp library. Progress is exposed for the UI."""

    def __init__(self):
        self.status = "idle"  # idle | installing | ready | error
        self.progress = 0.0
        self.message = ""
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def dir(self) -> Path:
        return ROOT / DEFAULT_TAG

    def library(self) -> Path:
        return self.dir / LIB

    def backend_name(self) -> str:
        marker = self.dir / "backend.txt"
        return marker.read_text().strip() if marker.exists() else _plan()[0]

    def installed(self) -> bool:
        if not self.library().exists():
            return False
        # Built without the graphics card for lack of tools, and the tools are there now: build again.
        return not (NO_GPU_TOOLS in self.backend_name() and _cuda_build_tools() is not None)

    def state(self) -> dict:
        if self.installed() and self.status != "installing":
            self.status = "ready"
        return {"status": self.status, "progress": self.progress, "message": self.message, "error": self.error,
                "version": DEFAULT_TAG, "backend": self.backend_name()}

    def ensure(self, background: bool = True) -> None:
        with self._lock:
            if self.installed() or self.status == "installing":
                return
            self.status, self.progress, self.error = "installing", 0.0, None
        if background:
            threading.Thread(target=self._install, daemon=True, name="sdcpp-install").start()
        else:
            self._install()

    def _install(self) -> None:
        tmp = self.dir.with_suffix(".partial")
        try:
            backend, how = _plan()
            if how == "unsupported":
                raise RuntimeError(MAC_TOO_OLD)
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            if how == "build":
                self._build(tmp)
            else:
                self._download(tmp, how)
            if not (tmp / LIB).exists():
                raise RuntimeError(f"{LIB} was not found in the stable-diffusion.cpp build")
            (tmp / "backend.txt").write_text(backend)
            if os.name != "nt":
                for p in tmp.iterdir():
                    if p.is_file() and (not p.suffix or ".so" in p.name or p.suffix == ".dylib"):
                        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            shutil.rmtree(self.dir, ignore_errors=True)
            tmp.rename(self.dir)
            self.progress, self.status, self.message = 1.0, "ready", "Ready"
        except Exception as e:
            log.exception("stable-diffusion.cpp install failed")
            shutil.rmtree(tmp, ignore_errors=True)
            self.status, self.error, self.message = "error", str(e), "Install failed"

    def _download(self, dest: Path, patterns: list[str]) -> None:
        self.message = "Finding the right picture engine for your computer"
        rel = httpx.get(f"https://api.github.com/repos/{REPO}/releases/tags/{DEFAULT_TAG}", timeout=30,
                        follow_redirects=True).json()
        assets = rel.get("assets", [])
        chosen = []
        for pat in patterns:
            a = next((a for a in assets if re.fullmatch(pat, a["name"])), None)
            if a is None:
                raise RuntimeError(f"No stable-diffusion.cpp build matches {pat} in release {DEFAULT_TAG}")
            chosen.append(a)
        total = sum(a["size"] for a in chosen) or 1
        done = 0
        for a in chosen:
            self.message = f"Downloading {a['name']}"
            buf = io.BytesIO()
            with httpx.stream("GET", a["browser_download_url"], follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    buf.write(chunk)
                    done += len(chunk)
                    self.progress = min(0.99, done / total)
            self.message = f"Unpacking {a['name']}"
            _extract_zip(buf, dest)

    def _build(self, dest: Path) -> None:
        """Build the library with CUDA from the pinned commit (Linux with an NVIDIA card)."""
        tools = _cuda_build_tools()
        if tools is None:
            raise RuntimeError("The tools to build the picture engine are missing.")
        src = ROOT / "src"
        env = dict(os.environ)
        env["PATH"] = str(Path(tools["nvcc"]).parent) + os.pathsep + env.get("PATH", "")
        self.message, self.progress = "Downloading the picture engine's source", 0.01
        if not (src / ".git").exists():
            shutil.rmtree(src, ignore_errors=True)
            _run([tools["git"], "clone", "--filter=blob:none", f"https://github.com/{REPO}.git", str(src)], env)
        _run([tools["git"], "-C", str(src), "fetch", "--filter=blob:none", "origin", COMMIT], env)
        _run([tools["git"], "-C", str(src), "checkout", "--force", COMMIT], env)
        _run([tools["git"], "-C", str(src), "submodule", "update", "--init", "--recursive"], env)
        self.message, self.progress = "Preparing the build", 0.05
        build = src / "build"
        shutil.rmtree(build, ignore_errors=True)
        _run([tools["cmake"], "-S", str(src), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release", "-DSD_CUDA=ON",
              "-DSD_BUILD_SHARED_LIBS=ON", "-DSD_BUILD_EXAMPLES=OFF",
              f"-DCMAKE_CUDA_COMPILER={tools['nvcc']}",
              # Only this computer's cards: building for every generation takes several times as long.
              "-DCMAKE_CUDA_ARCHITECTURES=native"], env)
        self.message = "Building the picture engine for your graphics card (this takes a while, once)"
        proc = subprocess.Popen([tools["cmake"], "--build", str(build), "--config", "Release", "-j",
                                 str(max(1, (os.cpu_count() or 2) - 1))],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail: list[str] = []
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-40:]
            m = re.match(r"\[\s*(\d+)%\]", line)
            if m:
                self.progress = 0.05 + 0.94 * int(m.group(1)) / 100
        if proc.wait() != 0:
            raise RuntimeError("Building the picture engine failed:\n" + "\n".join(tail[-12:]))
        for p in build.rglob("*"):
            if p.is_file() and re.search(r"\.so(\.\d+)*$", p.name):
                shutil.copy2(p, dest / p.name, follow_symlinks=True)


def _run(cmd: list[str], env: dict) -> None:
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {(r.stderr or r.stdout).strip()[-600:]}")


def _cuda_build_tools() -> dict | None:
    """Paths to nvcc, cmake, git and a C++ compiler, or None if any is missing."""
    nvcc = shutil.which("nvcc")
    if not nvcc:
        # NVIDIA's packages install to /usr/local/cuda-X.Y without touching PATH; Arch's to /opt/cuda.
        found = sorted(Path("/usr/local").glob("cuda*/bin/nvcc"), reverse=True) +             [p for p in [Path("/opt/cuda/bin/nvcc")] if p.exists()]
        nvcc = str(found[0]) if found else None
    tools = {"nvcc": nvcc, "cmake": shutil.which("cmake"), "git": shutil.which("git"),
             "cxx": shutil.which("c++") or shutil.which("g++")}
    return tools if all(tools.values()) else None


def _vulkan_available() -> bool:
    import ctypes.util

    return bool(ctypes.util.find_library("vulkan")) and not gpu.in_wsl()


def _plan() -> tuple[str, list[str] | str]:
    """(backend label, asset name regexes to download, "build", or "unsupported")."""
    system = platform.system()
    sha = re.escape(DEFAULT_TAG.rsplit("-", 1)[-1])
    has_nvidia = bool(gpu.list_gpus())
    if system == "Darwin":
        if _mac_major() < MAC_MIN:
            return f"not available (needs macOS {MAC_MIN})", "unsupported"
        # One file for both Apple Silicon and Intel Macs, despite its name.
        return "metal", [rf"sd-master-{sha}-bin-Darwin-macOS-[\d.]+-arm64\.zip"]
    if system == "Windows":
        if has_nvidia and gpu.cuda_driver_version():
            return "cuda 12", [rf"sd-master-{sha}-bin-win-cuda12-x64\.zip", r"cudart-sd-bin-win-cu12-x64\.zip"]
        return "cpu", [rf"sd-master-{sha}-bin-win-cpu-x64\.zip"]
    # Linux
    if has_nvidia and _cuda_build_tools():
        return "cuda (built here)", "build"
    if _vulkan_available():
        return "vulkan", [rf"sd-master-{sha}-bin-Linux-Ubuntu-[\d.]+-x86_64-vulkan\.zip"]
    label = f"cpu ({NO_GPU_TOOLS})" if has_nvidia else "cpu"
    return label, [rf"sd-master-{sha}-bin-Linux-Ubuntu-[\d.]+-x86_64\.zip"]


def unsupported() -> str | None:
    """Why the engine can't run on this computer at all, or None."""
    if platform.system() == "Darwin" and _mac_major() < MAC_MIN:
        return MAC_TOO_OLD
    return None


def _mac_major() -> int:
    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except ValueError:
        return 0


def gpu_help() -> str | None:
    """What to install to use the graphics card, when the engine was set up without it."""
    if NO_GPU_TOOLS not in installer.backend_name():
        return None
    drv = gpu.cuda_driver_version()
    package = f" (for your driver, cuda-toolkit-{drv[0]}-{drv[1]} or the newest below it)" if drv else ""
    return ("Pictures from this kind of model are made on the processor, which is very slow. To use your graphics "
            f"card, install the CUDA toolkit{package}, cmake and git, then use the model again: wanna.sh builds the "
            "engine for your card, once.")


def _extract_zip(buf: io.BytesIO, dest: Path) -> None:
    """Extract a release zip, flattening any folders (the libraries and their plugins sit side by side)."""
    buf.seek(0)
    with zipfile.ZipFile(buf) as z:
        for m in z.infolist():
            if m.is_dir():
                continue
            target = dest / Path(m.filename).name
            with z.open(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


installer = Installer()
