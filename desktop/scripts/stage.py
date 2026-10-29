"""Gather what the desktop app bundles into desktop/build/:

- backend/: the wanna.sh Python package (installed into the app's own environment on first run);
- ui/: the built interface (build it first: cd frontend && npm ci && npm run build);
- uv/: uv, which sets up Python and installs packages, pinned and checked against its published checksum.

    python3 desktop/scripts/stage.py [--target windows|macos-arm64|macos-x64]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = "0.12.19"
UV_ASSETS = {
    "windows": "uv-x86_64-pc-windows-msvc.zip",
    "macos-arm64": "uv-aarch64-apple-darwin.tar.gz",
    "macos-x64": "uv-x86_64-apple-darwin.tar.gz",
}

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "desktop" / "build"


def default_target() -> str:
    if platform.system() == "Darwin":
        return "macos-arm64" if platform.machine() == "arm64" else "macos-x64"
    return "windows"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def stage_uv(target: str) -> None:
    asset = UV_ASSETS[target]
    base = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"
    data = fetch(f"{base}/{asset}")
    expected = fetch(f"{base}/{asset}.sha256").decode().split()[0]
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"uv download checksum mismatch: {actual} != {expected}")
    out = BUILD / "uv"
    out.mkdir(parents=True)
    names = ("uv.exe",) if target == "windows" else ("uv",)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for m in z.namelist():
                if Path(m).name in names:
                    (out / Path(m).name).write_bytes(z.read(m))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for m in t.getmembers():
                if Path(m.name).name in names and m.isfile():
                    target_file = out / Path(m.name).name
                    target_file.write_bytes(t.extractfile(m).read())
                    target_file.chmod(0o755)
    if not any((out / n).exists() for n in names):
        raise SystemExit(f"uv wasn't found in {asset}")
    print(f"uv {UV_VERSION} ({asset}), sha256 ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=sorted(UV_ASSETS), default=default_target())
    args = ap.parse_args()

    ui = ROOT / "frontend" / "out"
    if not (ui / "index.html").exists():
        raise SystemExit("Build the interface first: cd frontend && npm ci && npm run build")

    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info")
    (BUILD / "backend").mkdir()
    shutil.copy2(ROOT / "backend" / "pyproject.toml", BUILD / "backend" / "pyproject.toml")
    shutil.copytree(ROOT / "backend" / "wanna", BUILD / "backend" / "wanna", ignore=ignore)
    shutil.copytree(ui, BUILD / "ui")
    stage_uv(args.target)
    size = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file())
    print(f"staged {BUILD} for {args.target}: {size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
