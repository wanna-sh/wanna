"""stable-diffusion.cpp engine: installs the library for this machine. Picture models in GGUF and single-file formats
(Qwen-Image and its editing models, and others) run on it, loaded into wanna.sh's own worker process through the
library's C interface (see workers/sdcpp_lib.py). Nothing of it listens on a port.

Where the library comes from:
- Windows and macOS: stable-diffusion.cpp's own release builds (CUDA 12, or the processor, on Windows; Metal on Mac).
- Linux with an NVIDIA card: a ready-made CUDA 12 build published on wanna.sh's GitHub releases by
  .github/workflows/sdcpp-linux-cuda.yml (stable-diffusion.cpp has none for Linux), with NVIDIA's CUDA runtime and
  cuBLAS from their packages on PyPI (cuda12_runtime.json). If that can't be downloaded, it's built here when the tools
  are there (CUDA toolkit, cmake, git and a C++ compiler).
- Otherwise on Linux: stable-diffusion.cpp's Vulkan or processor builds.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from pathlib import Path

import httpx

from .. import gpu
from ..config import ENGINES_DIR

log = logging.getLogger("wanna.sdcpp")

# Pinned, tested release and its commit (for the Linux build). Override both to try a newer one.
DEFAULT_TAG = os.environ.get("WANNA_SDCPP_TAG", "master-1043-3be2378")
COMMIT = os.environ.get("WANNA_SDCPP_COMMIT", "3be23788fc0c9f35a2c24b1211caae11d4a54dbc")
REPO = "leejet/stable-diffusion.cpp"
ROOT = ENGINES_DIR / "sdcpp"
LIB = {"Windows": "stable-diffusion.dll", "Darwin": "libstable-diffusion.dylib"}.get(platform.system(),
                                                                                    "libstable-diffusion.so")
# The ready-made Linux CUDA build of the pinned commit, published by .github/workflows/sdcpp-linux-cuda.yml under these
# names (the workflow reads them from here), with a .sha256 file beside it.
LINUX_CUDA_RELEASE = f"sdcpp-{COMMIT[:7]}-linux-cuda12"
LINUX_CUDA_ASSET = f"sdcpp-{COMMIT[:7]}-linux-x64-cuda12.tar.gz"
LINUX_CUDA_URL = os.environ.get(
    "WANNA_SDCPP_LINUX_CUDA_URL",
    f"https://github.com/wanna-sh/wanna/releases/download/{LINUX_CUDA_RELEASE}/{LINUX_CUDA_ASSET}")
CUDA12_RUNTIME = json.loads((Path(__file__).with_name("cuda12_runtime.json")).read_text())["wheels"]
# Marker for a build made without the graphics card because there was no way to get one for it.
NO_GPU_TOOLS = "no CUDA build tools"
# The Mac release is built for macOS 26 and newer (its library's minimum version, read from the file on 2026-11-03).
MAC_MIN = 26
MAC_TOO_OLD = (f"GGUF picture models need macOS {MAC_MIN} or newer on a Mac: the picture engine they run on "
               "(stable-diffusion.cpp) is only built for it. Other picture models work as usual.")
# Step-by-step instructions for installing the tools to build it.
GPU_HELP_URL = "https://wanna.sh/docs/guides/linux-gpu-pictures/"


class NotPublished(RuntimeError):
    """The ready-made Linux build of the pinned commit isn't on wanna.sh's releases (yet)."""


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
        # Set up without the graphics card, and there's a way to use it now (the tools appeared): set up again.
        return not (NO_GPU_TOOLS in self.backend_name() and NO_GPU_TOOLS not in _plan()[0])

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
            if how == "linux-cuda":
                try:
                    self._linux_cuda(tmp)
                except Exception as e:
                    if _cuda_build_tools() is None:
                        if isinstance(e, NotPublished):
                            raise RuntimeError("There's no ready-made picture engine for Linux in this version of "
                                               "wanna.sh yet. To use your graphics card now, install the CUDA toolkit, "
                                               "cmake and git, and wanna.sh builds it here.") from e
                        raise RuntimeError(f"Couldn't download the picture engine for your graphics card ({e}). "
                                           "Check your internet connection and try again.") from e
                    log.warning("Ready-made Linux CUDA build unavailable (%s); building it here", e)
                    shutil.rmtree(tmp, ignore_errors=True)
                    tmp.mkdir(parents=True)
                    backend = "cuda (built here)"
                    self._build(tmp)
            elif how == "build":
                self._build(tmp)
            else:
                self._release(tmp, how)
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

    def _fetch(self, url: str, name: str, done: int, total: int, sha256: str | None = None) -> tuple[Path, int]:
        """Download to a temporary file (not memory: some of these are hundreds of megabytes), moving the progress bar
        from done/total. Checks the SHA-256 when one is given. Returns the file and the new done count."""
        self.message = f"Downloading {name}"
        digest = hashlib.sha256()
        fd, path = tempfile.mkstemp(prefix="wanna-sdcpp-", dir=ROOT if ROOT.exists() else None)
        try:
            with os.fdopen(fd, "wb") as out, \
                    httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    self.progress = min(0.99, done / (total or 1))
            if sha256 and digest.hexdigest() != sha256.lower():
                raise RuntimeError(f"{name} didn't download intact (its checksum doesn't match). Try again.")
        except BaseException:
            Path(path).unlink(missing_ok=True)
            raise
        return Path(path), done

    def _release(self, dest: Path, patterns: list[str]) -> None:
        """stable-diffusion.cpp's own release builds (Windows, macOS, and Linux without CUDA)."""
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
        total, done = sum(a["size"] for a in chosen), 0
        for a in chosen:
            path, done = self._fetch(a["browser_download_url"], a["name"], done, total)
            try:
                self.message = f"Unpacking {a['name']}"
                with zipfile.ZipFile(path) as z:
                    _extract_flat(z, dest)
            finally:
                path.unlink(missing_ok=True)

    def _linux_cuda(self, dest: Path) -> None:
        """wanna.sh's ready-made Linux CUDA 12 build, and NVIDIA's CUDA runtime and cuBLAS from PyPI."""
        self.message = "Finding the right picture engine for your computer"
        with httpx.Client(follow_redirects=True, timeout=30) as c:
            r = c.get(LINUX_CUDA_URL + ".sha256")
            if r.status_code == 404:
                raise NotPublished("there's no ready-made Linux build of this version yet")
            r.raise_for_status()
            build_sha = r.text.split()[0]
            sizes = [int(c.head(u, timeout=30).headers.get("content-length") or 0)
                     for u in [LINUX_CUDA_URL, *(w["url"] for w in CUDA12_RUNTIME)]]
        total, done = sum(sizes), 0
        path, done = self._fetch(LINUX_CUDA_URL, LINUX_CUDA_ASSET, done, total, build_sha)
        try:
            self.message = f"Unpacking {LINUX_CUDA_ASSET}"
            with tarfile.open(path, "r:gz") as t:
                for m in t.getmembers():
                    if m.isfile():
                        with t.extractfile(m) as src, open(dest / Path(m.name).name, "wb") as out:
                            shutil.copyfileobj(src, out)
        finally:
            path.unlink(missing_ok=True)
        for wheel in CUDA12_RUNTIME:
            path, done = self._fetch(wheel["url"], wheel["name"], done, total, wheel["sha256"])
            try:
                self.message = f"Unpacking {wheel['name']}"
                with zipfile.ZipFile(path) as z:
                    for name in wheel["files"]:
                        with z.open(name) as src, open(dest / Path(name).name, "wb") as out:
                            shutil.copyfileobj(src, out)
            finally:
                path.unlink(missing_ok=True)

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
        found = sorted(Path("/usr/local").glob("cuda*/bin/nvcc"), reverse=True)
        found += [p for p in [Path("/opt/cuda/bin/nvcc")] if p.exists()]
        nvcc = str(found[0]) if found else None
    tools = {"nvcc": nvcc, "cmake": shutil.which("cmake"), "git": shutil.which("git"),
             "cxx": shutil.which("c++") or shutil.which("g++")}
    return tools if all(tools.values()) else None


def _vulkan_available() -> bool:
    import ctypes.util

    return bool(ctypes.util.find_library("vulkan")) and not gpu.in_wsl()


def _plan() -> tuple[str, list[str] | str]:
    """(backend label, asset name regexes to download, or "linux-cuda", "build" or "unsupported")."""
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
    drv = gpu.cuda_driver_version() or (0, 0)
    if has_nvidia and drv >= (12, 0) and platform.machine().lower() in ("x86_64", "amd64"):
        return "cuda 12", "linux-cuda"
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
    """What to install to use the graphics card, when the engine was set up without it (an NVIDIA driver too old for
    CUDA 12, or a Linux computer that isn't x86-64)."""
    if NO_GPU_TOOLS not in installer.backend_name():
        return None
    drv = gpu.cuda_driver_version()
    if drv and drv < (12, 0):
        return ("Pictures from this kind of model are made on the processor, which is very slow, because your "
                f"graphics driver only supports CUDA {drv[0]}.{drv[1]}. Update your NVIDIA driver to use your "
                "graphics card.")
    package = f" (for your driver, cuda-toolkit-{drv[0]}-{drv[1]} or the newest below it)" if drv else ""
    return ("Pictures from this kind of model are made on the processor, which is very slow. To use your graphics "
            f"card, install the CUDA toolkit{package}, cmake and git, then use the model again: wanna.sh builds the "
            "engine for your card, once.")


def _extract_flat(z: zipfile.ZipFile, dest: Path) -> None:
    """Extract a release zip, flattening any folders (the libraries and their plugins sit side by side)."""
    for m in z.infolist():
        if m.is_dir():
            continue
        with z.open(m) as src, open(dest / Path(m.filename).name, "wb") as out:
            shutil.copyfileobj(src, out)


installer = Installer()
