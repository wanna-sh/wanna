"""Chat models bigger than this computer's memory: running them from the drive, and estimating how fast that is.

llama.cpp maps the model file into memory instead of copying it in: the operating system reads each part from the
drive the first time it's needed and keeps what fits in spare memory. A mixture-of-experts model uses only a few of
its experts for each token, so only those are read. A dense model reads every weight for every token, which from a
drive is very slow.

Estimates come from the model file itself (how many bytes each token touches: the parts every token uses plus its
share of the experts), how much of that the graphics cards and memory can hold, and measured speeds of this
computer's drive, memory and graphics cards. Once a model has run, the speed measured in its log is shown instead.
"""

from __future__ import annotations

import ctypes
import json
import logging
import mmap
import os
import re
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import psutil

from . import gpu
from .config import HOME, MODELS_DIR, hf_token, load_settings

log = logging.getLogger("wanna.streaming")

GB = 1e9
MEASURED_PATH = HOME / "hardware.json"
# Memory other programs and the system keep for themselves; the rest can cache the model.
RAM_KEEP_FRACTION = 0.25
RAM_KEEP_MIN = 2 * 1024**3
# Graphics memory the driver, the desktop and llama.cpp's working buffers take on each card, beyond the model.
GPU_OVERHEAD = int(1.4 * 1024**3)
# Share of measured bandwidth llama.cpp reaches when reading weights, and its fixed cost per layer for each token on
# a graphics card. Measured with llama.cpp b11963 and Llama 3.2 1B Q8_0: 28.5 tokens a second on an i5-14500 with
# DDR4-3200 (38 GB/s measured, 29.5 used), 257 on an RTX 3070 (448 GB/s peak).
CPU_EFFICIENCY = 0.77
GPU_EFFICIENCY = 0.8
GPU_LAYER_SECONDS = 0.064e-3
# llama.cpp reads a prompt in batches of this many tokens.
UBATCH = 512
# Tensors llama.cpp may read from the file on demand instead of keeping in memory are bigger than this.
LAZY_MIN = 4 * 1024**3
# How unevenly a model's router picks experts decides how often the ones in memory are the ones a token needs. Evenly
# (Kimi K3 is trained that way), a cache holding a share of the experts serves that share of reads. Many models reuse a
# few experts much more: with Qwen3-30B-A3B on a PC with 32 GB of memory, a cache holding 23% of the experts served
# about 84% of reads, which is share ** 0.12. The fast end of the estimate assumes that.
ROUTING_SKEW = 0.12
# Measured with Qwen3-30B-A3B BF16 read from an NVMe drive, on an i5-14500 with an RTX 3070 and an RTX 3060:
# - Reading a prompt, the processor works through its experts at about this many bytes of expert weights times tokens
#   a second, on top of reading them (715 tokens took 24.7 s, 15.4 s of it reading).
PROMPT_COMPUTE_RATE = 214e9
# - Starting, llama.cpp copies what goes on the graphics cards out of the mapped file at about this share of the
#   one-thread reading speed the drive measurement finds (16.6 GB in about 100 s, against 0.77 GB/s measured).
LOAD_COPY_SHARE = 0.21


# --- what a token touches, from the GGUF header ------------------------------------------------------------------------

_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_KEEP = re.compile(r"^(general\.(architecture|alignment)|[\w.-]+\.(expert_count|expert_used_count|block_count|"
                   r"embedding_length|attention\.head_count|attention\.head_count_kv|attention\.key_length|"
                   r"attention\.value_length|attention\.kv_lora_rank|rope\.dimension_count))$")
SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$")


class _Reader:
    """Reads a GGUF header front to back through read_at(offset, size), fetching in chunks that double in size
    (headers run from a few KB to several MB, when they carry the tokenizer)."""

    def __init__(self, read_at, chunk: int):
        self.read_at, self.chunk = read_at, chunk
        self.buf, self.start, self.pos = b"", 0, 0

    def read(self, n: int) -> bytes:
        while self.pos + n > self.start + len(self.buf):
            # Keep only what's still unread (nothing, after a skip past the end), then fetch more after it.
            end = self.start + len(self.buf)
            self.buf = self.buf[self.pos - self.start:] if self.pos < end else b""
            self.start = self.pos
            end = self.start + len(self.buf)
            more = self.read_at(end, max(self.chunk, self.pos + n - end))
            if not more:
                raise ValueError("the file ended inside its header")
            self.buf += more
            self.chunk *= 2
        out = self.buf[self.pos - self.start:self.pos - self.start + n]
        self.pos += n
        return out

    def skip(self, n: int) -> None:
        self.pos += n


def _parse(read_at, file_size: int, chunk: int = 1 << 18) -> tuple[dict, list[tuple[str, int]]]:
    """(wanted metadata, [(tensor name, bytes)]) from one GGUF file. Tensor sizes come from the offsets."""
    r = _Reader(read_at, chunk)
    if r.read(4) != b"GGUF":
        raise ValueError("not a GGUF file")
    version, n_tensors, n_kv = struct.unpack("<IQQ", r.read(20))
    if version < 2:
        raise ValueError("GGUF version 1 isn't supported")

    def read_str() -> str:
        (n,) = struct.unpack("<Q", r.read(8))
        return r.read(n).decode("utf-8", errors="replace")

    def value(t: int, keep: bool):
        if t in _SCALARS:
            fmt = _SCALARS[t]
            raw = r.read(struct.calcsize(fmt))
            return struct.unpack(fmt, raw)[0] if keep else None
        if t == 8:
            if keep:
                return read_str()
            (n,) = struct.unpack("<Q", r.read(8))
            r.skip(n)
            return None
        if t == 9:
            inner, n = struct.unpack("<IQ", r.read(12))
            if inner in _SCALARS:
                r.skip(struct.calcsize(_SCALARS[inner]) * n)  # per-layer arrays: not needed
            else:
                for _ in range(n):
                    value(inner, False)
            return None
        raise ValueError(f"unknown GGUF value type {t}")

    kv: dict = {}
    for _ in range(n_kv):
        key = read_str()
        (t,) = struct.unpack("<I", r.read(4))
        keep = bool(_KEEP.match(key))
        v = value(t, keep)
        if keep and v is not None:
            kv[key] = v
    offsets = []
    for _ in range(n_tensors):
        name = read_str()
        (nd,) = struct.unpack("<I", r.read(4))
        r.skip(8 * nd + 4)  # dimensions and type: the offsets give the sizes
        (off,) = struct.unpack("<Q", r.read(8))
        offsets.append((off, name))
    align = int(kv.get("general.alignment") or 32)
    data_start = (r.pos + align - 1) // align * align
    offsets.sort()
    ends = [o for o, _ in offsets[1:]] + [file_size - data_start]
    return kv, [(name, max(0, end - off)) for (off, name), end in zip(offsets, ends)]


def _summarise(parts: list[tuple[dict, list[tuple[str, int]]]]) -> dict:
    kv: dict = {}
    tensors: list[tuple[str, int]] = []
    for k, t in parts:
        kv.update(k)
        tensors += t
    arch = kv.get("general.architecture", "")
    a = lambda key: kv.get(f"{arch}.{key}")  # noqa: E731
    experts = sum(b for n, b in tensors if "_exps." in n)
    # Token embeddings are looked up a row at a time and stay with the processor; they're never read whole.
    embed = sum(b for n, b in tensors if n.startswith(("token_embd.", "per_layer_token_embd.")))
    # llama.cpp reads per-layer embeddings over 4 GiB from the file row by row (lazy reading, in the architectures
    # that allow it, e.g. Gemma 4 and Qwen3.8 Flash Next), so they never take memory. Elsewhere this is 0.
    lazy = sum(b for n, b in tensors if n.startswith("per_layer_token_embd.") and b > LAZY_MIN)
    total = sum(b for _, b in tensors)
    layers = a("block_count") or 0
    # Conversation memory per token: compressed (MLA) when the model has a latent rank, else keys and values per head.
    if a("attention.kv_lora_rank"):
        kv_token = layers * (a("attention.kv_lora_rank") + (a("rope.dimension_count") or 64)) * 2
    else:
        heads = a("attention.head_count") or 0
        kv_heads = a("attention.head_count_kv") or heads
        head_dim = a("attention.key_length") or ((a("embedding_length") or 0) // heads if heads else 0)
        kv_token = layers * kv_heads * (head_dim + (a("attention.value_length") or head_dim)) * 2
    return {
        "architecture": arch,
        "total": total,
        "experts": experts,
        "embed": embed,
        "lazy": lazy,
        "always": total - experts - embed,
        "n_expert": int(a("expert_count") or 0),
        "n_used": int(a("expert_used_count") or 0),
        "layers": int(layers),
        # Hybrid models keep memory only in some layers, so this can overstate it; that errs on the safe side.
        "kv_per_token": int(kv_token) or None,
    }


def _shards(path: str) -> list[Path]:
    p = Path(path)
    m = SPLIT_RE.search(p.name)
    if not m:
        return [p]
    n = int(m.group(2))
    return [p.with_name(SPLIT_RE.sub(f"-{i:05d}-of-{n:05d}.gguf", p.name)) for i in range(1, n + 1)]


def _local_one(path: Path) -> tuple[dict, list[tuple[str, int]]]:
    with open(path, "rb") as f:
        def read_at(off: int, n: int) -> bytes:
            f.seek(off)
            return f.read(n)

        return _parse(read_at, path.stat().st_size)


@lru_cache(maxsize=32)
def layout_local(path: str) -> dict:
    """What each token touches, for an installed model (all parts of a split model)."""
    return _summarise([_local_one(p) for p in _shards(path)])


@lru_cache(maxsize=64)
def layout_remote(repo_id: str, files: tuple[tuple[str, int], ...]) -> dict:
    """The same for a version on Hugging Face, from its headers only (a few MB, fetched with range requests)."""
    import httpx
    from huggingface_hub import hf_hub_url

    token = hf_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def one(item: tuple[str, int]):
        path, size = item
        url = hf_hub_url(repo_id, path)
        with httpx.Client(follow_redirects=True, timeout=60, headers=headers) as c:
            def read_at(off: int, n: int) -> bytes:
                for attempt in range(3):
                    try:
                        r = c.get(url, headers={"Range": f"bytes={off}-{off + n - 1}"})
                        r.raise_for_status()
                        return r.content
                    except httpx.HTTPError:
                        if attempt == 2:
                            raise
                        time.sleep(1 + attempt)
                return b""

            return _parse(read_at, size)

    with ThreadPoolExecutor(8) as ex:
        return _summarise(list(ex.map(one, files)))


# --- measured speeds of this computer ----------------------------------------------------------------------------------

_measure_lock = threading.Lock()
_measuring = threading.Event()


def _load_measured() -> dict:
    try:
        return json.loads(MEASURED_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_measured(patch: dict) -> None:
    data = _load_measured()
    data.update(patch)
    MEASURED_PATH.write_text(json.dumps(data, indent=2))


def _device() -> int:
    return os.stat(MODELS_DIR).st_dev


def drive() -> dict | None:
    """The last measurement of the drive models are stored on, if it's still the same drive."""
    d = _load_measured().get("drive")
    return d if d and d.get("device") == _device() else None


def measuring() -> bool:
    return _measuring.is_set()


def measure_drive_soon() -> None:
    """Measure the models drive in the background (about ten seconds), unless that's already happening."""
    with _measure_lock:
        if _measuring.is_set():
            return
        _measuring.set()

    def run():
        try:
            _save_measured({"drive": {"device": _device(), **_measure_drive(MODELS_DIR), "at": time.time()}})
        except Exception as e:
            log.warning("Couldn't measure the drive: %s", e)
            _save_measured({"drive": {"device": _device(), "error": str(e), "at": time.time()}})
        finally:
            _measuring.clear()

    threading.Thread(target=run, daemon=True, name="measure-drive").start()


class _Uncached:
    """A file opened so reads and writes skip the operating system's cache, to measure the drive itself."""

    def __init__(self, path: Path, write: bool):
        self.path = path
        if os.name == "nt":
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateFileW.restype = ctypes.c_void_p
            k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            for name in ("ReadFile", "WriteFile"):
                getattr(k32, name).argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                               ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            self.k32 = k32
            generic = 0x40000000 if write else 0x80000000  # GENERIC_WRITE / GENERIC_READ
            share = 0x7  # read, write and delete
            disposition = 2 if write else 3  # CREATE_ALWAYS / OPEN_EXISTING
            flags = 0x20000000 | (0x80000000 if write else 0x10000000)  # NO_BUFFERING | WRITE_THROUGH or RANDOM_ACCESS
            self.handle = k32.CreateFileW(str(path), generic, share, None, disposition, flags, None)
            if self.handle in (None, ctypes.c_void_p(-1).value):
                raise OSError(ctypes.get_last_error(), "couldn't open the file without caching")
            self.fd = None
        else:
            mode = (os.O_WRONLY | os.O_CREAT | os.O_TRUNC) if write else os.O_RDONLY
            self.direct = hasattr(os, "O_DIRECT")
            try:
                self.fd = os.open(path, mode | (os.O_DIRECT if self.direct else 0), 0o600)
            except OSError:
                # Some file systems (e.g. Windows drives inside WSL) refuse direct I/O; drop the cache by hand instead.
                self.direct = False
                self.fd = os.open(path, mode, 0o600)
            if sys.platform == "darwin":
                import fcntl

                fcntl.fcntl(self.fd, 48, 1)  # F_NOCACHE

    def _overlapped(self, offset: int):
        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                        ("Offset", ctypes.c_uint32), ("OffsetHigh", ctypes.c_uint32), ("hEvent", ctypes.c_void_p)]

        return OVERLAPPED(None, None, offset & 0xFFFFFFFF, offset >> 32, None)

    def pread(self, buf, offset: int) -> int:
        if self.fd is None:
            done = ctypes.c_uint32(0)
            ov = self._overlapped(offset)
            addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
            if not self.k32.ReadFile(self.handle, addr, len(buf), ctypes.byref(done), ctypes.byref(ov)):
                raise OSError(ctypes.get_last_error(), "read failed")
            return done.value
        return os.preadv(self.fd, [buf], offset)

    def pwrite(self, buf, offset: int) -> int:
        if self.fd is None:
            done = ctypes.c_uint32(0)
            ov = self._overlapped(offset)
            addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
            if not self.k32.WriteFile(self.handle, addr, len(buf), ctypes.byref(done), ctypes.byref(ov)):
                raise OSError(ctypes.get_last_error(), "write failed")
            return done.value
        return os.pwritev(self.fd, [buf], offset)

    def close(self) -> None:
        if self.fd is None:
            self.k32.CloseHandle(self.handle)
            return
        if not self.direct and hasattr(os, "posix_fadvise"):
            os.fsync(self.fd)
            os.posix_fadvise(self.fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(self.fd)


def _measure_drive(folder: Path, size: int = 2 << 30, chunk: int = 4 << 20, seconds: float = 3.0) -> dict:
    """Write a 2 GB test file past the cache, then read random 4 MB pieces of it two ways: straight from the drive
    (the drive's own speed), and through a memory map, the way llama.cpp reads a model it can't hold in memory."""
    import random

    if psutil.disk_usage(str(folder)).free < size * 3:
        raise OSError("not enough free space to measure the drive")
    test = folder / ".wanna-drive-test"
    buf = mmap.mmap(-1, chunk)  # page-aligned, as uncached I/O requires
    buf.write(os.urandom(chunk))  # random, so drives that compress can't cheat
    try:
        f = _Uncached(test, write=True)
        try:
            for off in range(0, size, chunk):
                f.pwrite(buf, off)
        finally:
            f.close()

        threads = min(8, os.cpu_count() or 4)
        pieces = list(range(0, size, chunk))
        # Each reading gets its own third of the file, so none finds pieces another one brought into the cache.
        third = len(pieces) // 3
        first, second, last = pieces[:third], pieces[third:2 * third], pieces[2 * third:]
        random.shuffle(first)
        random.shuffle(second)

        def run(read_one, offsets: list[int], n: int = threads) -> float:
            todo = list(reversed(offsets))
            lock = threading.Lock()
            done = [0]
            stop = time.perf_counter() + seconds

            def worker():
                while time.perf_counter() < stop:
                    with lock:
                        if not todo:
                            return
                        off = todo.pop()
                    done_now = read_one(off)
                    with lock:
                        done[0] += done_now

            t0 = time.perf_counter()
            with ThreadPoolExecutor(n) as ex:
                for _ in range(n):
                    ex.submit(worker)
            return done[0] / (time.perf_counter() - t0)

        # Straight from the drive, random pieces from several threads.
        readers = threading.local()
        opened: list = []

        def direct(off: int) -> int:
            if not hasattr(readers, "f"):
                readers.f, readers.buf = _Uncached(test, write=False), mmap.mmap(-1, chunk)
                opened.append((readers.f, readers.buf))
            return readers.f.pread(readers.buf, off)

        try:
            direct_speed = run(direct, first)
        finally:
            for f, b in opened:
                f.close()
                b.close()
        with open(test, "rb") as fh:
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_COPY)
            base = ctypes.addressof(ctypes.c_char.from_buffer(mm))
            local = threading.local()

            def mapped(off: int) -> int:
                if not hasattr(local, "dst"):
                    local.dst = ctypes.create_string_buffer(chunk)
                ctypes.memmove(local.dst, base + off, chunk)  # page faults read from the drive, outside the GIL
                return chunk

            try:
                # Random pieces from several threads: how a model's experts are read while it writes.
                mapped_speed = run(mapped, second)
                # One thread in order: how llama.cpp copies weights from the file to a graphics card, when it starts
                # and when it reads a prompt (the experts it keeps with the processor go to the card in batches).
                copy_speed = run(mapped, last, 1)
            finally:
                mm.close()
        return {"direct": direct_speed, "mapped": mapped_speed, "copy": copy_speed}
    finally:
        buf.close()
        try:
            test.unlink()
        except OSError:
            pass


@lru_cache(maxsize=1)
def ram_bandwidth() -> float:
    """Bytes a second this computer's processor reads from memory, with several threads (half a second)."""
    import numpy as np

    threads = min(8, os.cpu_count() or 4)
    n = 32 << 20  # well past the processor's caches
    arrays = [np.ones(n, np.uint8) for _ in range(threads)]  # written, so every page is real memory
    done = [0] * threads
    stop = time.perf_counter() + 0.5

    def worker(i: int):
        a = arrays[i].view(np.uint64)
        while time.perf_counter() < stop:
            a.max()  # reads every byte, writes nothing
            done[i] += n

    t0 = time.perf_counter()
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(worker, range(threads)))
    return sum(done) / (time.perf_counter() - t0)


# --- the estimate ------------------------------------------------------------------------------------------------------

def setting_on() -> bool:
    return bool(load_settings().get("stream_from_drive"))


def ram_cache(total: int | None = None) -> int:
    """Memory that can hold parts of a model, leaving room for the system and other programs."""
    total = total or psutil.virtual_memory().total
    return max(0, int(total - max(total * RAM_KEEP_FRACTION, RAM_KEEP_MIN)))


def estimate(layout: dict, context: int | None = None, gpus: list[int] | None = None) -> dict:
    """How this model would run here: where its parts go, what each token reads from where, and the speed."""
    context = context or load_settings()["default_context"]
    cards = [g for g in gpu.list_gpus() if gpus is None or g["index"] in gpus]
    apple = gpu.apple_silicon()
    kv = (layout.get("kv_per_token") or 0) * context
    ram_total = psutil.virtual_memory().total

    # Graphics cards first: the parts every token uses, then as many experts as fit (as llama.cpp's planner does).
    gpu_room = 0 if apple else sum(max(0, g["memory_total"] - GPU_OVERHEAD) for g in cards)
    gpu_room = max(0, gpu_room - kv)
    always_gpu = min(layout["always"], gpu_room)
    experts_gpu = min(layout["experts"], gpu_room - always_gpu)
    always_cpu = layout["always"] - always_gpu
    experts_cpu = layout["experts"] - experts_gpu
    share = layout["n_used"] / layout["n_expert"] if layout["n_expert"] else 1.0

    # Then memory: the parts every token uses stay cached; experts share what's left. Routing spreads tokens over
    # the experts, so the share of experts found in memory is about the share that fits.
    cache = ram_cache(ram_total) - (0 if cards and not apple else kv) - (layout["embed"] - layout.get("lazy", 0))
    always_cached = min(always_cpu, max(0, cache))
    left = max(0, cache - always_cached)
    hit = min(1.0, left / experts_cpu) if experts_cpu else 1.0

    def reads(h: float) -> dict:
        """Bytes one token reads from each place, when a share h of the experts it needs are in memory."""
        return {
            "gpu": always_gpu + experts_gpu * share,
            "ram": always_cached + experts_cpu * share * h,
            "drive": (always_cpu - always_cached) + experts_cpu * share * (1 - h),
        }

    per_token = reads(hit)
    # Reads that favour some experts find them in memory more often; see ROUTING_SKEW.
    hit_fast = min(1.0, hit ** ROUTING_SKEW) if 0 < hit < 1 else hit
    if per_token["drive"] > 0:
        mode = "drive"
    elif per_token["ram"] > 0:
        mode = "ram"
    else:
        mode = "gpu"

    measured = drive()
    if mode == "drive" and not (measured and measured.get("copy")) and not measuring():
        measure_drive_soon()  # never measured, or measured before copying speed was
    drive_speed = (measured or {}).get("mapped")
    copy_speed = (measured or {}).get("copy")
    ram_bw = ram_bandwidth()
    gpu_bw = _gpu_bandwidth(cards) or ram_bw

    out = {
        "mode": mode,
        "bytes_per_token": {k: int(v) for k, v in per_token.items()},
        "model_bytes": layout["total"],
        "moe": layout["n_expert"] > 0,
        "experts": {"total": layout["n_expert"], "used": layout["n_used"]},
        "memory_hit": round(hit, 3),
        "memory_hit_fast": round(hit_fast, 3),
        "context": context,
        "speeds": {"drive": drive_speed, "drive_direct": (measured or {}).get("direct"), "drive_copy": copy_speed,
                   "ram": ram_bw, "gpu": gpu_bw},
        "measuring_drive": measuring(),
        "setting_on": setting_on(),
        "drive_error": (measured or {}).get("error"),
        "seconds_per_token": None,
        "tokens_per_second": None,
        "tokens_per_second_fast": None,
        "prompt_seconds": None,
        "short_prompt_seconds": None,
        "first_prompt_seconds": None,
        "start_seconds": None,
    }
    if mode == "drive" and not (drive_speed and copy_speed):
        return out  # the drive's speed decides it; back once it's measured

    cpu_bw = ram_bw * CPU_EFFICIENCY

    def seconds(r: dict) -> float:
        t = r["ram"] / cpu_bw
        if r["gpu"]:
            t += r["gpu"] / (gpu_bw * GPU_EFFICIENCY) + layout["layers"] * GPU_LAYER_SECONDS
        if r["drive"]:
            t += r["drive"] / drive_speed
        return t

    t = seconds(per_token)
    out["seconds_per_token"] = t
    out["tokens_per_second"] = 1 / t if t else None
    if mode == "drive":
        out["tokens_per_second_fast"] = 1 / seconds(reads(hit_fast))

        def prompt(tokens: int, h: float) -> float:
            # A prompt's tokens go to many experts at once. llama.cpp reads it in batches of 512 (started with
            # --no-op-offload, so the processor's threads do it): each batch reads the experts it needs that aren't in
            # memory, then works through them.
            batches = -(-tokens // UBATCH)
            touched = 1 - (1 - share) ** min(tokens, UBATCH)
            from_drive = (always_cpu - always_cached) + experts_cpu * touched * (1 - h)
            from_ram = always_cached + experts_cpu * touched * h
            work = tokens * experts_cpu * share / PROMPT_COMPUTE_RATE
            return batches * (from_drive / drive_speed + from_ram / cpu_bw) + work

        out["prompt_seconds"] = prompt(UBATCH, hit)  # per 512 tokens
        out["short_prompt_seconds"] = prompt(20, hit)  # a short message, about 15 words
        out["first_prompt_seconds"] = prompt(20, 0.0)  # the first one after starting, with nothing in memory yet
        # Starting, llama.cpp asks for the whole file to be read ahead, then copies what goes on the graphics cards.
        out["start_seconds"] = (layout["total"] / drive_speed
                                + (always_gpu + experts_gpu) / (copy_speed * LOAD_COPY_SHARE))
    return out


def _gpu_bandwidth(cards: list[dict]) -> float | None:
    """Combined memory bandwidth of these cards, weighted by their memory (llama.cpp splits layers that way)."""
    bws = [(gpu.memory_bandwidth(g["index"]), g["memory_total"]) for g in cards]
    bws = [(b, m) for b, m in bws if b]
    if not bws:
        return None
    # Layers run one card after another: time adds up, so combine as a weighted harmonic mean.
    total = sum(m for _, m in bws)
    return total / sum(m / b for b, m in bws)


def needs_drive(model: dict, gpus: list[int] | None) -> bool:
    """Whether this chat model is bigger than the memory it could have here (graphics cards in `gpus`, None for all,
    plus system memory), so it has to be read from the drive as it runs. Judged on this computer's totals, like the
    ratings, so models that happen to be loaded don't change the answer."""
    try:
        layout = layout_local(model["path"])
    except (OSError, ValueError):
        return False
    total = layout["total"] - layout.get("lazy", 0)  # read from the file as needed, never held in memory
    cards = [g for g in gpu.list_gpus() if gpus is None or g["index"] in gpus]
    room = 0 if gpu.apple_silicon() else sum(max(0, g["memory_total"] - GPU_OVERHEAD) for g in cards)
    return total > room + ram_cache()


def refusal(model: dict) -> str:
    title = (model.get("meta") or {}).get("title") or model["id"]
    return (f"{title} is bigger than this computer's graphics and system memory together, so it can only run by "
            "reading from your drive while it writes, which is very slow. To allow that, turn on \"Run models "
            "bigger than memory\" in Settings, or choose a smaller version.")


def for_variant(repo_id: str, variant_id: str, context: int | None = None) -> dict:
    """The estimate for one version of a model on Hugging Face, before downloading it."""
    from . import hub

    variant = next((v for v in hub.details(repo_id)["variants"] if v["id"] == variant_id), None)
    if variant is None:
        raise ValueError("No such version of this model.")
    sizes = {s.rfilename: s.size or 0 for s in hub._model_info(repo_id).siblings or []}
    # The vision projector is small and sits with the graphics card; the estimate is about the language model.
    files = tuple((f, sizes.get(f, 0)) for f in variant["files"] if "mmproj" not in f.lower())
    return estimate(layout_remote(repo_id, files), context)


def for_model(model: dict, context: int | None = None) -> dict:
    """The estimate for an installed chat model, with its measured speed once it has run here."""
    from .readiness import measured_speed

    out = estimate(layout_local(model["path"]), context)
    out["measured_tokens_per_second"] = measured_speed(model["id"])
    return out
