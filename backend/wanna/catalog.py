"""Browse every runnable model on Hugging Face and rate how well each one will run on this computer.

Ratings use the machine's total graphics and system memory (not what happens to be free right now),
so they don't change as models are started and stopped.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import psutil

from . import gpu, hub

log = logging.getLogger("wanna.catalog")

GB = 1e9
# Bytes per parameter for a Q4_K_M GGUF (about 4.85 bits per weight), the "Balanced" choice we recommend.
Q4_BYTES_PER_PARAM = 0.606
# Graphics memory the driver and desktop keep for themselves on each card.
GPU_RESERVE = int(0.4 * GB)

TASK_QUERIES = {
    "chat": [{"filter": "gguf"}],
    "image": [{"filter": "diffusers", "pipeline_tag": "text-to-image"}],
    "video": [{"filter": "diffusers", "pipeline_tag": "text-to-video"},
              {"filter": "diffusers", "pipeline_tag": "image-to-video"}],
    "speech": [{"filter": "transformers", "pipeline_tag": "text-to-speech"}],
    "sound": [{"filter": "transformers", "pipeline_tag": "text-to-audio"}],
    "transcribe": [{"filter": "transformers", "pipeline_tag": "automatic-speech-recognition"}],
    "embed": [{"filter": ["gguf", "feature-extraction"]}, {"filter": ["gguf", "sentence-similarity"]}],
}
EXPAND = ["gguf", "safetensors", "config", "siblings", "downloads", "likes", "trendingScore", "createdAt",
          "pipeline_tag", "library_name", "tags", "gated"]
SORTS = {"popular": "downloads", "trending": "trending_score", "newest": "created_at", "liked": "likes"}

# Models we have run end to end with wanna.sh on real hardware.
TESTED = {
    "bartowski/Llama-3.2-3B-Instruct-GGUF",
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    "facebook/mms-tts-eng",
    "openai/whisper-small",
    "facebook/musicgen-small",
    "openai/whisper-large-v3-turbo",
    "facebook/wav2vec2-base-960h",
    "UsefulSensors/moonshine-tiny",
    "suno/bark-small",
}


# --- hardware budget & ratings ---------------------------------------------

def budget() -> dict:
    gpus = gpu.list_gpus()
    usable = [max(0, g["memory_total"] - GPU_RESERVE) for g in gpus]
    best = max(range(len(gpus)), key=lambda i: usable[i]) if gpus else None
    return {
        "gpus": [{"index": g["index"], "name": g["name"], "memory": g["memory_total"]} for g in gpus],
        "best_gpu": usable[best] if gpus else 0,
        "best_gpu_name": _short(gpus[best]["name"]) if gpus else None,
        "all_gpus": sum(usable),
        "ram": psutil.virtual_memory().total,
    }


def _short(name: str) -> str:
    return name.removeprefix("NVIDIA ").removeprefix("GeForce ")


def runtime_need(task: str, weights: int) -> int:
    """Graphics memory a model needs while running: weights plus working memory."""
    if task == "chat":
        return int(weights * 1.1 + 0.6 * GB)  # KV cache for an 8K conversation + compute buffers
    if task == "image":
        return int(weights * 1.2 + 1.0 * GB)
    if task == "video":
        return int(weights * 1.3 + 2.0 * GB)
    return int(weights * 1.2 + 0.5 * GB)


def rate(task: str, weights: int | None, b: dict | None = None) -> dict:
    """A plain-language verdict for running `weights` bytes of `task` model on this computer."""
    b = b or budget()
    if not weights:
        return {"level": "unknown", "label": "Size unknown", "detail": "Hugging Face doesn't list this model's size.",
                "need": None}
    need = runtime_need(task, weights)
    out = {"need": need}
    splits = task in ("chat", "image", "video")  # Python audio workers use a single card
    if not b["gpus"]:
        if weights * 1.2 <= b["ram"] * 0.7:
            return {**out, "level": "slow", "label": "Runs, but slowly",
                    "detail": "No graphics card found, so it will run on the processor."}
        return {**out, "level": "no", "label": "Too big for this computer",
                "detail": f"Needs about {_gb(weights * 1.2)} of memory; this computer has {_gb(b['ram'])}."}
    if need <= b["best_gpu"]:
        return {**out, "level": "great", "label": "Runs great here",
                "detail": f"Needs about {_gb(need)}. Fits on your {b['best_gpu_name']}."}
    if splits and len(b["gpus"]) > 1 and need <= b["all_gpus"]:
        return {**out, "level": "good", "label": "Runs well here",
                "detail": f"Needs about {_gb(need)}, so it shares the work between your graphics cards."}
    if task == "chat" and need <= b["all_gpus"] + b["ram"] * 0.5:
        return {**out, "level": "slow", "label": "Runs, but slowly",
                "detail": f"Needs about {_gb(need)}. Part of it runs on the processor, so replies come slowly."}
    if task != "chat" and weights * 1.15 <= b["ram"] * 0.6:
        return {**out, "level": "slow", "label": "Runs, but slowly",
                "detail": f"Needs about {_gb(need)}, more than your graphics cards have. "
                          "It streams from system memory, which is much slower."}
    room = b["all_gpus"] if splits else b["best_gpu"]
    return {**out, "level": "no", "label": "Too big for this computer",
            "detail": f"Needs about {_gb(need)}; your graphics memory is {_gb(room)}."}


def _gb(n: float) -> str:
    return f"{n / GB:.0f} GB" if n >= 10 * GB else f"{n / GB:.1f} GB"


RUNS_WELL = ("great", "good")


# --- which voice, transcription and music models actually work ----------------

# Model types run end to end through wanna.sh's generic pipelines. Being in transformers' registry
# isn't enough: some types (e.g. gradium_phonon_tts) need their own processor to build a prompt.
# Add a type here only after generating real output with it.
VERIFIED_TYPES = {
    "speech": {"vits", "bark"},                        # facebook/mms-tts-*, suno/bark-*
    "transcribe": {"whisper", "wav2vec2", "moonshine"},  # openai/whisper-*, facebook/wav2vec2-*, UsefulSensors/moonshine-*
    "sound": {"musicgen"},                            # facebook/musicgen-* (incl. stereo)
}


def transformers_runnable(task: str, model_type: str | None, tags) -> bool:
    if not model_type or "custom_code" in (tags or []):
        return False
    return model_type in VERIFIED_TYPES.get(task, set())


# --- browsing ---------------------------------------------------------------

_cache: dict[tuple, tuple[float, list]] = {}
_CACHE_TTL = 600


def _candidates(task: str, query: str, sort: str, count: int, max_params: float | None) -> list:
    key = (task, query, sort, count, max_params)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    a = hub.api()
    out, seen = [], set()
    for q in TASK_QUERIES[task]:
        kw = dict(q, search=query or None, sort=SORTS.get(sort, "downloads"), limit=count, expand=EXPAND)
        if task == "chat" and max_params:
            kw["num_parameters"] = f"min:0,max:{max_params:.0f}B"
        for m in a.list_models(**kw):
            if m.id not in seen:
                seen.add(m.id)
                out.append(m)
    _cache[key] = (time.time(), out)
    return out


_FIXTURE = re.compile(r"(tiny-random|internal-testing|hf-internal|dummy|-test$|testing/)", re.IGNORECASE)


def _quick(m, task: str, b: dict) -> dict | None:
    """Rate a list entry from listing data alone. None = not runnable by wanna.sh."""
    if _FIXTURE.search(m.id):
        return None  # tiny models made for automated tests, not for people
    tags = m.tags or []
    if task == "chat":
        g = m.gguf or {}
        if not hub.is_chat_gguf(m.id, m.pipeline_tag, tags) or not g.get("context_length") or not g.get("total"):
            return None  # image/music/embedding GGUFs, or no metadata to size it
        # Some uploads carry wrong metadata; the size in the name ("27B") is a useful floor.
        params = max(g["total"], _params_from_name(m.id))
        weights = int(params * Q4_BYTES_PER_PARAM)
        return {"weights": weights, "params": params, "verdict": rate(task, weights, b),
                "vision": m.pipeline_tag in ("image-text-to-text", "any-to-any")}
    if task == "embed":
        g = m.gguf or {}
        if not hub.is_embed_gguf(m.id, m.pipeline_tag, tags) or not g.get("total"):
            return None
        weights = int(g["total"] * 1.07)  # Q8_0, the usual choice for small embedding models
        return {"weights": weights, "params": g["total"], "verdict": rate(task, weights, b)}
    if task in ("image", "video"):
        files = {s.rfilename for s in (m.siblings or [])}
        if "model_index.json" not in files:
            return None  # LoRAs and original-format checkpoints that diffusers can't load directly
        return {"weights": None, "params": None, "verdict": None}  # sized from file list later
    if task == "transcribe" and hub.NOT_TRANSCRIPTION_NAME.search(m.id):
        return None
    model_type = (m.config or {}).get("model_type") if isinstance(m.config, dict) else None
    if not transformers_runnable(task, model_type, tags):
        return None
    params = getattr(m.safetensors, "total", None) if m.safetensors else None
    # Voices load at full precision; transcription and music at half precision.
    weights = int(params * (4 if task == "speech" else 2)) if params else None
    return {"weights": weights, "params": params, "verdict": rate(task, weights, b)}


_NAME_PARAMS = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)[bB](?![a-zA-Z])")


def _params_from_name(repo_id: str) -> int:
    """Largest "<n>B" in a repo name, e.g. "Qwen3-30B-A3B" -> 30e9. 0 when absent."""
    found = [float(x) for x in _NAME_PARAMS.findall(repo_id.split("/")[-1])]
    return int(max(found) * 1e9) if found else 0


def _diffusers_info(repo_id: str) -> tuple[int | None, bool]:
    """(loaded weight bytes, needs a starting picture) from the repo's file list and model_index.json."""
    try:
        d = hub.details(repo_id)
    except Exception:
        return None, False
    v = d["variants"][0] if d.get("variants") else None
    return (v.get("weights") if v else None), bool(d.get("needs_image"))


def browse(task: str, query: str = "", sort: str = "popular", fits_only: bool = True,
           limit: int = 24, offset: int = 0) -> dict:
    b = budget()
    want = offset + limit
    max_params = None
    if task == "chat" and fits_only:
        # Ask Hugging Face only for models small enough to fit (at Balanced quality).
        max_params = (b["all_gpus"] or b["ram"] * 0.5) / Q4_BYTES_PER_PARAM / 1e9
    count = min(400, max(60, want * 4))
    cands = _candidates(task, query, sort, count, max_params)

    rows = []
    pending = []  # diffusers entries that need a file listing to be sized
    for m in cands:
        q = _quick(m, task, b)
        if q is None:
            continue
        rows.append((m, q))
        if task in ("image", "video"):
            pending.append(m.id)

    if pending:
        # Size only as many as we might show, in parallel. Results are cached by hub.details.
        need_n = min(len(pending), want * (3 if fits_only else 1) + 6, 60)
        with ThreadPoolExecutor(8) as ex:
            sizes = dict(zip(pending[:need_n], ex.map(_diffusers_info, pending[:need_n])))
        for m, q in rows:
            if m.id in sizes:
                q["weights"], q["needs_image"] = sizes[m.id]
                q["verdict"] = rate(task, q["weights"], b) if q["weights"] else None
        rows = [(m, q) for m, q in rows if m.id in sizes and q["verdict"]]

    results = []
    for m, q in rows:
        if fits_only and q["verdict"]["level"] not in RUNS_WELL:
            continue
        results.append(_row(m, task, q))
    curated = {c["repo_id"]: c for c in hub.CURATED}
    for r in results:
        c = curated.get(r["repo_id"])
        if c:
            r["title"], r["why"] = c["title"], c["why"]
    return {"results": results[offset:want], "has_more": len(results) > want or len(cands) >= count,
            "budget": _public_budget(b)}


def _row(m, task: str, q: dict) -> dict:
    return {
        "repo_id": m.id,
        "author": m.id.split("/")[0],
        "name": m.id.split("/")[-1],
        "title": _pretty(m.id.split("/")[-1]),
        "why": None,
        "task": task,
        "task_label": hub.TASKS[task]["label"],
        "downloads": m.downloads or 0,
        "likes": m.likes or 0,
        "gated": bool(m.gated),
        "params": q.get("params"),
        "weights": q.get("weights"),
        "verdict": q["verdict"],
        "vision": q.get("vision", False),
        "needs_image": q.get("needs_image", False),
        "tested": m.id in TESTED,
        "created": m.created_at.isoformat() if getattr(m, "created_at", None) else None,
    }


def _pretty(name: str) -> str:
    for suffix in ("-GGUF", "-gguf", "_GGUF", "-Diffusers", "-diffusers"):
        name = name.removesuffix(suffix)
    return name.replace("_", " ").replace("-", " ")


def _public_budget(b: dict) -> dict:
    return {"gpus": [{"name": _short(g["name"]), "memory": g["memory"]} for g in b["gpus"]],
            "all_gpus": b["all_gpus"], "best_gpu": b["best_gpu"], "ram": b["ram"], "wsl": gpu.in_wsl()}


_REMIX_WORDS = {"abliterated", "uncensored", "heretic", "gsq", "rco", "aggressive", "quantized", "instruct", "it",
                "chat", "gguf", "imatrix", "i1", "hf", "diffusers"}
_SIZE = re.compile(r"^\d+(\.\d+)?[bm]$")
_VERSION = re.compile(r"^(v?\d+(\.\d+)*|\d{4})$")


def _family(r: dict) -> str:
    """Same model, different uploads: "unsloth/Qwen3.8-27B-GGUF" and "huihui/Huihui-Qwen3.8-27B-abliterated"."""
    tokens = [t for t in re.split(r"[-_\s]+", r["name"].lower()) if t and t not in _REMIX_WORDS]
    size = next((t for t in tokens if _SIZE.match(t)), None)
    # The model's own name usually mixes letters and digits ("qwen3.8"); otherwise take the first word + version.
    base = next((t for t in tokens if re.search(r"[a-z]", t) and re.search(r"\d", t)
                 and not _SIZE.match(t) and not _VERSION.match(t)), None)
    if base is None:
        words = [t for t in tokens if not _SIZE.match(t) and not _VERSION.match(t)]
        version = next((t for t in tokens if _VERSION.match(t) and not t.startswith("v")), None)
        base = " ".join(filter(None, [words[0] if words else "", version]))
        if not size:
            return " ".join(words[:3])
    return " ".join(filter(None, [base, size]))


def overview(query: str = "", per_task: int = 4) -> dict:
    """Top models per task for the "Everything" view, one per model family."""
    b = budget()
    with ThreadPoolExecutor(6) as ex:
        futures = {t: ex.submit(browse, t, query, "popular", True, per_task * 4, 0) for t in hub.TASKS}
    sections = []
    for t, f in futures.items():
        try:
            picked, seen = [], set()
            for r in f.result()["results"]:
                fam = _family(r)
                if fam not in seen:
                    seen.add(fam)
                    picked.append(r)
            sections.append({"task": t, "results": picked[:per_task]})
        except Exception as e:
            log.warning("overview for %s failed: %s", t, e)
            sections.append({"task": t, "results": [], "error": str(e)})
    return {"sections": sections, "budget": _public_budget(b)}
