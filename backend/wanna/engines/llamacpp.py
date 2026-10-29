"""llama.cpp engine: installs a prebuilt llama-server for this machine and runs it per model."""

from __future__ import annotations

import io
import logging
import os
import platform
import re
import shutil
import stat
import tarfile
import threading
import zipfile
from pathlib import Path

import httpx

from .. import gpu
from ..config import ENGINES_DIR

log = logging.getLogger("wanna.llamacpp")

# Pinned, tested release. Override with WANNA_LLAMACPP_TAG to try a newer one.
DEFAULT_TAG = os.environ.get("WANNA_LLAMACPP_TAG", "b11963")
ROOT = ENGINES_DIR / "llamacpp"
EXE = "llama-server.exe" if os.name == "nt" else "llama-server"


class Installer:
    """Downloads and unpacks the right llama.cpp build. Progress is exposed for the UI."""

    def __init__(self):
        self.status = "idle"  # idle | installing | ready | error
        self.progress = 0.0
        self.message = ""
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def dir(self) -> Path:
        return ROOT / DEFAULT_TAG

    def installed(self) -> bool:
        return (self.dir / EXE).exists()

    def binary(self) -> Path:
        return self.dir / EXE

    def state(self) -> dict:
        if self.installed() and self.status != "installing":
            self.status = "ready"
        return {
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "version": DEFAULT_TAG,
            "backend": self.backend_name(),
        }

    def backend_name(self) -> str:
        marker = self.dir / "backend.txt"
        return marker.read_text().strip() if marker.exists() else _pick_backend()[0]

    def ensure(self, background: bool = True) -> None:
        with self._lock:
            if self.installed() or self.status == "installing":
                return
            self.status, self.progress, self.error = "installing", 0.0, None
        if background:
            threading.Thread(target=self._install, daemon=True, name="llamacpp-install").start()
        else:
            self._install()

    def _install(self) -> None:
        try:
            backend, patterns = _pick_backend()
            self.message = "Finding the right engine for your computer"
            rel = httpx.get(
                f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{DEFAULT_TAG}",
                timeout=30, follow_redirects=True,
            ).json()
            assets = rel.get("assets", [])
            chosen = []
            for pat in patterns:
                a = next((a for a in assets if re.fullmatch(pat, a["name"])), None)
                if a is None:
                    raise RuntimeError(f"No llama.cpp build matches {pat} in release {DEFAULT_TAG}")
                chosen.append(a)
            total = sum(a["size"] for a in chosen) or 1
            done = 0
            tmp = self.dir.with_suffix(".partial")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
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
                _extract_flat(buf, a["name"], tmp)
            (tmp / "backend.txt").write_text(backend)
            exe = tmp / EXE
            if not exe.exists():
                raise RuntimeError("llama-server was not found in the downloaded build")
            if os.name != "nt":
                for p in tmp.iterdir():
                    if p.is_file() and not p.suffix:
                        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            shutil.rmtree(self.dir, ignore_errors=True)
            tmp.rename(self.dir)
            self.progress, self.status, self.message = 1.0, "ready", "Ready"
        except Exception as e:
            log.exception("llama.cpp install failed")
            self.status, self.error, self.message = "error", str(e), "Install failed"


def _pick_backend() -> tuple[str, list[str]]:
    """Return (backend label, asset name regexes) for this OS, CPU and GPU driver."""
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    drv = gpu.cuda_driver_version()
    has_nvidia = bool(gpu.list_gpus())
    tag = re.escape(DEFAULT_TAG)

    if system == "Darwin":
        return "metal", [rf"llama-{tag}-bin-macos-{arch}\.tar\.gz"]

    if system == "Windows":
        if has_nvidia and drv:
            cuda = r"13\.\d+" if drv >= (13, 1) else r"12\.\d+"
            return f"cuda (driver {drv[0]}.{drv[1]})", [
                rf"llama-{tag}-bin-win-cuda-{cuda}-{arch}\.zip",
                rf"cudart-llama-bin-win-cuda-{cuda}-{arch}\.zip",
            ]
        return "cpu", [rf"llama-{tag}-bin-win-cpu-{arch}\.zip"]

    # Linux
    if has_nvidia and drv:
        # Prefer CUDA 13 only when the driver is new enough for the build's minor version,
        # otherwise the CUDA 12.8 build works on any 12.8+ driver.
        if drv >= (13, 4):
            cuda = r"13\.\d+"
        else:
            cuda = r"12\.\d+"
        return f"cuda (driver {drv[0]}.{drv[1]})", [
            rf"llama-{tag}-bin-ubuntu-cuda-{cuda}-{arch}\.tar\.gz",
            rf"cudart-llama-{tag}-bin-ubuntu-cuda-{cuda}-{arch}\.tar\.gz",
        ]
    return "cpu", [rf"llama-{tag}-bin-ubuntu-{arch}\.tar\.gz"]


def _extract_flat(buf: io.BytesIO, name: str, dest: Path) -> None:
    """Extract an archive, dropping its single top-level folder."""
    buf.seek(0)
    if name.endswith(".zip"):
        with zipfile.ZipFile(buf) as z:
            for m in z.infolist():
                if m.is_dir():
                    continue
                target = dest / Path(m.filename).name
                with z.open(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return
    with tarfile.open(fileobj=buf, mode="r:gz") as t:
        for m in t.getmembers():
            rel = Path(m.name)
            if len(rel.parts) < 2:
                continue
            target = dest / Path(*rel.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            if m.issym():
                if target.exists() or target.is_symlink():
                    target.unlink()
                os.symlink(m.linkname, target)
            elif m.isfile():
                with t.extractfile(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(m.mode | stat.S_IRUSR | stat.S_IWUSR)


def server_command(
    model_path: str, port: int, context: int, gpus: list[int], split: list[float] | None,
    mmproj: str | None = None, alias: str | None = None, extra: list[str] | None = None,
    gpu_layers: int | None = None, embedding: bool = False, pooling: str | None = None,
) -> tuple[list[str], dict]:
    """Build the llama-server command line and environment for a model placement."""
    cmd = [
        str(installer.binary()),
        "--model", model_path,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--ctx-size", str(context),
        "--jinja",
        "--no-webui",
    ]
    if alias:
        cmd += ["--alias", alias]
    if mmproj:
        cmd += ["--mmproj", mmproj]
    if embedding:
        # Embedding models read a whole passage in one batch, so the batch sizes must cover the context.
        cmd += ["--embedding", "--batch-size", str(context), "--ubatch-size", str(context)]
        if pooling:
            cmd += ["--pooling", pooling]
    env = dict(os.environ)
    lib_dir = str(installer.dir)
    env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if gpus:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, gpus))
        # With a plan from llama-fit-params we pass its layer count; otherwise "auto" with --fit on lets
        # oversized models spill to the CPU instead of failing.
        if gpu_layers is not None:
            cmd += ["--n-gpu-layers", str(gpu_layers)]
        if len(gpus) > 1 and split:
            cmd += ["--split-mode", "layer", "--tensor-split", ",".join(str(s) for s in split)]
    else:
        env["CUDA_VISIBLE_DEVICES"] = ""
        cmd += ["--n-gpu-layers", "0"]
    cmd += extra or []
    return cmd, env


installer = Installer()
