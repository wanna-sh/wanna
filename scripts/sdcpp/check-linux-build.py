"""Checks a Linux CUDA build of stable-diffusion.cpp before it's published (no graphics card needed):

1. With NVIDIA's CUDA runtime and cuBLAS from the wheels wanna.sh downloads (backend/wanna/engines/cuda12_runtime.json,
   checksums checked), every library's dependencies resolve, apart from the graphics driver's libcuda.so.1, which
   comes with the driver on each computer.
2. The library loads, and wanna.sh's ctypes binding matches its structs (workers/sdcpp_lib.py check_layout).
3. It's the pinned commit.

    python3 check-linux-build.py <build folder> <commit>

The library links the graphics driver's libcuda.so.1, so loading it needs one. On a computer without a driver (CI), set
SDCPP_DRIVER_STUB to a folder holding NVIDIA's stub as libcuda.so.1 (the CUDA toolkit's lib64/stubs/libcuda.so): it's
used to load the library, never for the dependency check.
"""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import urllib.request
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend" / "wanna"


def dependencies(build: Path) -> dict:
    """Step 1. Returns the environment that finds every library, for step 2."""
    runtime = Path(tempfile.mkdtemp(prefix="cuda12-runtime-"))
    for wheel in json.loads((BACKEND / "engines" / "cuda12_runtime.json").read_text())["wheels"]:
        data = urllib.request.urlopen(wheel["url"]).read()
        if hashlib.sha256(data).hexdigest() != wheel["sha256"]:
            sys.exit(f"{wheel['name']}: checksum doesn't match cuda12_runtime.json")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in wheel["files"]:
                (runtime / Path(name).name).write_bytes(z.read(name))
        print(f"ok  {wheel['name']}: {', '.join(Path(n).name for n in wheel['files'])}")

    env = {**os.environ, "LD_LIBRARY_PATH": f"{build}:{runtime}"}
    libs = sorted(build.glob("*.so*"))
    for needed in ("libstable-diffusion.so", "libggml.so", "libggml-base.so"):
        if not (build / needed).exists():
            sys.exit(f"{needed} is missing from {build}: the build is incomplete")
    if not list(build.glob("libggml-cuda*.so")):
        sys.exit(f"ggml's CUDA plugin (libggml-cuda.so) is missing from {build}")
    missing = {}
    for lib in libs:
        out = subprocess.run(["ldd", str(lib)], env=env, capture_output=True, text=True).stdout
        gone = [line.split()[0] for line in out.splitlines() if "not found" in line and "libcuda.so.1" not in line]
        if gone:
            missing[lib.name] = gone
    if missing:
        sys.exit(f"Unresolved dependencies: {missing}")
    print(f"ok  the dependencies of all {len(libs)} libraries resolve (libcuda.so.1 comes with the driver)")
    return env


def load(build: Path, commit: str) -> None:
    """Steps 2 and 3, in a process started with LD_LIBRARY_PATH set (the loader only reads it at start)."""
    # The binding imports the library's file name from the engine module, which needs wanna.sh's dependencies; a
    # stand-in with just that name is enough here.
    sys.modules["wanna"] = types.ModuleType("wanna")
    sys.modules["wanna.engines"] = types.ModuleType("wanna.engines")
    sys.modules["wanna.engines.sdcpp"] = types.SimpleNamespace(LIB="libstable-diffusion.so")
    spec = importlib.util.spec_from_file_location("wanna.workers.sdcpp_lib", BACKEND / "workers" / "sdcpp_lib.py")
    binding = importlib.util.module_from_spec(spec)
    binding.__package__ = "wanna.workers"
    spec.loader.exec_module(binding)
    os.chdir(build)  # ggml finds its plugins beside the program or in the current folder, as in wanna.sh's worker
    lib = binding.load(build)
    binding.check_layout(lib)
    print("ok  wanna.sh's binding matches the library's structs")
    built = lib.sd_commit().decode()
    if not commit.startswith(built):
        sys.exit(f"Built from {built}, expected {commit}")
    print(f"ok  stable-diffusion.cpp {built}")


if __name__ == "__main__":
    folder, pinned = Path(sys.argv[1]).resolve(), sys.argv[2]
    if sys.argv[3:] == ["--load"]:
        load(folder, pinned)
    else:
        env = dependencies(folder)
        stub = os.environ.get("SDCPP_DRIVER_STUB")
        if stub:
            env["LD_LIBRARY_PATH"] += f":{stub}"
            print(f"..  loading with NVIDIA's driver stub from {stub} (no graphics driver here)")
        subprocess.run([sys.executable, __file__, str(folder), pinned, "--load"], env=env, check=True)
