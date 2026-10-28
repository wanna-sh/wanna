"""Hugging Face discovery: search, classify into friendly tasks, and pick which files to download."""

from __future__ import annotations

import re
from functools import lru_cache

from huggingface_hub import HfApi

from .config import hf_token

# Friendly task taxonomy shown in the UI.
TASKS = {
    "chat": {"label": "Chat & write", "blurb": "Talk to an assistant, write, summarise and code."},
    "image": {"label": "Create images", "blurb": "Turn a description into a picture."},
    "video": {"label": "Create videos", "blurb": "Turn a description (or a picture) into a short clip."},
    "speech": {"label": "Read text aloud", "blurb": "Turn text into a natural sounding voice."},
    "transcribe": {"label": "Speech to text", "blurb": "Turn recordings into written text."},
    "sound": {"label": "Music & sound effects", "blurb": "Generate music or sound from a description."},
}

# Hugging Face pipeline tags -> our task.
PIPELINE_TO_TASK = {
    "text-generation": "chat",
    "image-text-to-text": "chat",
    "text2text-generation": "chat",
    "text-to-image": "image",
    "text-to-video": "video",
    "image-to-video": "video",
    "text-to-speech": "speech",
    "text-to-audio": "sound",
    "automatic-speech-recognition": "transcribe",
}

# Hand-picked starters for people who don't know where to begin.
# All verified to exist and be ungated on 2026-10-28.
CURATED = [
    {"repo_id": "unsloth/Qwen3-4B-Instruct-2507-GGUF", "task": "chat", "title": "Qwen3 4B",
     "why": "Smart, fast all-rounder. Great first chat model for 6GB+ GPUs."},
    {"repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF", "task": "chat", "title": "Llama 3.2 3B",
     "why": "Small and quick. Runs on almost anything."},
    {"repo_id": "unsloth/gemma-3-4b-it-GGUF", "task": "chat", "title": "Gemma 3 4B",
     "why": "Friendly writing style and it can look at pictures you attach."},
    {"repo_id": "bartowski/Qwen2.5-7B-Instruct-GGUF", "task": "chat", "title": "Qwen2.5 7B",
     "why": "Bigger and smarter. Best with 8GB+ of GPU memory."},
    {"repo_id": "stabilityai/sdxl-turbo", "task": "image", "title": "SDXL Turbo",
     "why": "Makes a picture in about a second. Good for quick ideas."},
    {"repo_id": "stable-diffusion-v1-5/stable-diffusion-v1-5", "task": "image", "title": "Stable Diffusion 1.5",
     "why": "The classic. Small, light and works on modest GPUs."},
    {"repo_id": "segmind/SSD-1B", "task": "image", "title": "SSD-1B",
     "why": "A lighter SDXL with high quality 1024px images."},
    {"repo_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "task": "video", "title": "Wan 2.1 (1.3B)",
     "why": "Small text-to-video model that fits on a single consumer GPU."},
    {"repo_id": "Lightricks/LTX-Video", "task": "video", "title": "LTX-Video",
     "why": "Fast video generation from text or a starting picture."},
    {"repo_id": "facebook/mms-tts-eng", "task": "speech", "title": "MMS English voice",
     "why": "Tiny, instant English text-to-speech."},
    {"repo_id": "suno/bark-small", "task": "speech", "title": "Bark (small)",
     "why": "Expressive voice that can laugh, sigh and sing a little."},
    {"repo_id": "openai/whisper-small", "task": "transcribe", "title": "Whisper small",
     "why": "Accurate transcription in 99 languages, fast on any GPU."},
    {"repo_id": "openai/whisper-large-v3-turbo", "task": "transcribe", "title": "Whisper large v3 turbo",
     "why": "Top accuracy transcription that is still fast."},
    {"repo_id": "facebook/musicgen-small", "task": "sound", "title": "MusicGen (small)",
     "why": "Describe a style of music and get a short track."},
]

WEIGHT_EXT = (".safetensors", ".bin", ".ckpt", ".pt", ".pth", ".onnx", ".onnx_data", ".msgpack", ".h5", ".gguf", ".pb",
              ".tflite", ".mlmodel")
# Sample media and docs in model repos that a pipeline never needs.
JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".wav", ".mp3", ".pdf")

QUANT_RE = re.compile(
    r"(?:^|[-_.])((?:UD-)?(?:I?Q[1-8](?:_[0-9A-Z]+)*|F16|BF16|F32|FP16|FP8|MXFP4(?:_MOE)?))(?=[-_.]|$)",
    re.IGNORECASE,
)
SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$")
# GGUF files that ship alongside a model but aren't one: importance matrices and speculative-decoding drafts.
NOT_A_MODEL_RE = re.compile(r"(imatrix|(^|[/_.-])mtp([/_.-]|$)|(^|[/_.-])draft([/_.-]|$))", re.IGNORECASE)

# Rough quality ladder used to explain quantisation in plain words.
QUANT_TIERS = [
    (("Q2", "IQ1", "IQ2"), 1, "Tiny", "Smallest download, noticeably less smart."),
    (("Q3", "IQ3"), 2, "Small", "Small, a bit less smart."),
    (("Q4", "IQ4", "MXFP4"), 3, "Balanced", "Best balance of size and smarts. Recommended."),
    (("Q5",), 4, "Good", "Slightly smarter, a bit bigger."),
    (("Q6",), 5, "Great", "Almost full quality."),
    (("Q8", "FP8"), 6, "Excellent", "Practically full quality, large."),
    (("F16", "BF16", "FP16", "F32"), 7, "Original", "Full quality, very large."),
]


def api() -> HfApi:
    return HfApi(token=hf_token())


def _tier(quant: str | None) -> dict:
    q = (quant or "").upper().removeprefix("UD-")
    for prefixes, rank, label, desc in QUANT_TIERS:
        if q.startswith(prefixes):
            return {"rank": rank, "label": label, "description": desc}
    return {"rank": 3, "label": "Standard", "description": ""}


# GGUF uploads that carry a context length but aren't chat models: music/audio LMs, VAEs, embedders.
NOT_CHAT_TAGS = {"music-generation", "text-to-music", "text2music", "music", "audio", "text-to-speech", "tts",
                 "text-to-image", "image-generation", "diffusion", "vae", "embedding", "embeddings",
                 "sentence-similarity", "feature-extraction", "reranker", "text-ranking"}
NOT_TRANSCRIPTION_NAME = re.compile(r"(aligner|alignment)", re.IGNORECASE)
NOT_CHAT_NAME = re.compile(r"(ace-?step|embedding|reranker|[-_]tts[-_]|[-_]vae\b|whisper|text-to-speech)", re.IGNORECASE)


def is_chat_gguf(repo_id: str, pipeline: str | None, tags) -> bool:
    # Google tags its official Gemma 4 GGUFs "any-to-any" (they take text, pictures and audio).
    if pipeline not in (None, "text-generation", "image-text-to-text", "text2text-generation", "any-to-any"):
        return False
    return not (NOT_CHAT_TAGS & set(tags or [])) and not NOT_CHAT_NAME.search(repo_id)


def classify(info) -> tuple[str | None, str | None]:
    """Return (task, engine) for a ModelInfo, or (None, None) if we can't run it."""
    tags = set(info.tags or [])
    siblings = [s.rfilename for s in (info.siblings or [])]
    has_gguf = "gguf" in tags or any(f.endswith(".gguf") for f in siblings)
    pipeline = info.pipeline_tag
    library = info.library_name

    if has_gguf and is_chat_gguf(info.id, pipeline, tags):
        return "chat", "llamacpp"
    # Other repos may also ship .gguf files (e.g. a voice model); classify them by what they are.
    task = PIPELINE_TO_TASK.get(pipeline or "")
    if task is None:
        if "model_index.json" in siblings:
            return "image", "diffusers"
        return None, None
    if task in ("image", "video"):
        # Only diffusers-format repos load directly; LoRAs and single-file checkpoints don't.
        return (task, "diffusers") if "model_index.json" in siblings else (None, None)
    if "custom_code" in tags:
        return None, None
    if task == "chat":
        if library == "transformers" or "config.json" in siblings:
            return "chat", "transformers"
        return None, None
    from .catalog import transformers_runnable

    if task == "transcribe" and NOT_TRANSCRIPTION_NAME.search(info.id):
        return None, None  # forced aligners match text to audio; they don't transcribe

    config = info.config if isinstance(getattr(info, "config", None), dict) else {}
    if not transformers_runnable(task, config.get("model_type"), tags):
        return None, None
    return task, "transformers"


def _summary(info, task, engine, curated=None) -> dict:
    return {
        "repo_id": info.id,
        "author": info.id.split("/")[0],
        "name": info.id.split("/")[-1],
        "title": (curated or {}).get("title") or info.id.split("/")[-1],
        "why": (curated or {}).get("why"),
        "task": task,
        "task_label": TASKS[task]["label"] if task else None,
        "engine": engine,
        "downloads": info.downloads or 0,
        "likes": info.likes or 0,
        "gated": bool(info.gated),
        "updated": info.last_modified.isoformat() if getattr(info, "last_modified", None) else None,
        "pipeline_tag": info.pipeline_tag,
    }


@lru_cache(maxsize=256)
def _model_info(repo_id: str):
    return api().model_info(repo_id, files_metadata=True)


def details(repo_id: str) -> dict:
    """Everything the UI needs to show a model page and offer download choices."""
    info = _model_info(repo_id)
    task, engine = classify(info)
    curated = next((c for c in CURATED if c["repo_id"] == repo_id), None)
    if curated and not task:
        task = curated["task"]
    out = _summary(info, task, engine, curated)
    files = [{"path": s.rfilename, "size": s.size or 0} for s in (info.siblings or [])]
    out["supported"] = task is not None
    out["license"] = (info.card_data or {}).get("license") if info.card_data else None
    out["tags"] = [t for t in (info.tags or []) if ":" not in t][:20]

    if engine == "llamacpp":
        out["variants"] = gguf_variants(files)
        for v in out["variants"]:
            v["weights"] = v["size"]
    elif engine in ("diffusers", "transformers"):
        components = _diffusers_components(repo_id) if engine == "diffusers" else None
        chosen, variant = select_repo_files(files, engine, components)
        size = sum(f["size"] for f in files if f["path"] in chosen)
        out["variants"] = [
            {
                "id": "default",
                "label": "Standard" if not variant else "Half precision (smaller, same quality)",
                "description": "Downloads everything this model needs.",
                "files": chosen,
                "size": size,
                "weights": _loaded_weights(info, task, engine, variant, files, chosen),
                "variant": variant,
                "rank": 3,
            }
        ]
    else:
        out["variants"] = []

    from .catalog import TESTED, budget, rate

    b = budget()
    for v in out["variants"]:
        v["verdict"] = rate(task, v["weights"], b) if task else None
    out["tested"] = repo_id in TESTED
    out["needs_image"] = task == "video" and _needs_image(repo_id)
    out["recommended"] = recommend_variant(out["variants"])
    out["verdict"] = next((v["verdict"] for v in out["variants"] if v["id"] == out["recommended"]), None)
    return out


def _loaded_weights(info, task, engine, variant, files, chosen) -> int:
    """Bytes the weights take once loaded (we load at 16-bit, except voices which load at full precision)."""
    weight_bytes = sum(f["size"] for f in files if f["path"] in chosen and f["path"].endswith(WEIGHT_EXT))
    st = getattr(info, "safetensors", None)
    params = getattr(st, "total", None) if st else None
    dtypes = set((getattr(st, "parameters", None) or {}).keys()) if st else set()
    if engine == "transformers" and params:
        return int(params * (4 if task == "speech" else 2))
    if engine == "diffusers" and not variant and dtypes == {"F32"}:
        return weight_bytes // 2  # stored as fp32, loaded as fp16/bf16
    return weight_bytes


def gguf_variants(files: list[dict]) -> list[dict]:
    """Group .gguf files into downloadable choices (handles multi-part splits and vision projectors)."""
    groups: dict[str, dict] = {}
    mmproj = [f for f in files if f["path"].endswith(".gguf") and "mmproj" in f["path"].lower()]
    for f in files:
        p = f["path"]
        if not p.endswith(".gguf") or "mmproj" in p.lower() or NOT_A_MODEL_RE.search(p):
            continue
        key = SPLIT_RE.sub(".gguf", p)
        g = groups.setdefault(key, {"id": key, "files": [], "size": 0})
        g["files"].append(p)
        g["size"] += f["size"]

    # Prefer a compact, broadly compatible projector for vision models.
    projector = None
    if mmproj:
        def proj_rank(f):
            name = f["path"].upper()
            return (0 if "F16" in name else 1 if "BF16" in name else 2 if "Q8" in name else 3, f["size"])
        projector = sorted(mmproj, key=proj_rank)[0]

    out = []
    for key, g in groups.items():
        m = QUANT_RE.search(key.rsplit("/", 1)[-1].removesuffix(".gguf"))
        quant = m.group(1).upper() if m else None
        tier = _tier(quant)
        files_ = sorted(g["files"])
        size = g["size"]
        if projector:
            files_.append(projector["path"])
            size += projector["size"]
        out.append(
            {
                "id": key,
                "quant": quant,
                "label": f"{tier['label']}" + (f" ({quant})" if quant else ""),
                "description": tier["description"],
                "rank": tier["rank"],
                "files": files_,
                "size": size,
                "vision": bool(projector),
            }
        )
    if len(out) > 2:
        # Backstop for helper files with unusual names: a real version is never a fraction of the others.
        sizes = sorted(v["size"] for v in out)
        median = sizes[len(sizes) // 2]
        out = [v for v in out if v["size"] >= median * 0.25]
    out.sort(key=lambda v: (v["rank"], v["size"]))
    return out


def recommend_variant(variants: list[dict]) -> str | None:
    """Best quality that runs well here; otherwise the smallest Balanced-or-better that runs at all."""
    if not variants:
        return None
    ok = [v for v in variants if (v.get("verdict") or {}).get("level") in ("great", "good")]
    if ok:
        # Quality first (capped at Q8; F16 is rarely worth double the size). Sharing two cards costs
        # little speed, so fitting on one card only breaks ties. Below Balanced only if nothing else fits.
        good_quality = [v for v in ok if v["rank"] >= 3] or ok
        return max(good_quality,
                   key=lambda v: (min(v["rank"], 6), v["verdict"]["level"] == "great", -v["size"]))["id"]
    slow = [v for v in variants if (v.get("verdict") or {}).get("level") == "slow" and v["rank"] >= 3]
    pool = slow or [v for v in variants if v["rank"] >= 3] or variants
    return min(pool, key=lambda v: v["size"])["id"]


@lru_cache(maxsize=256)
def _model_index(repo_id: str) -> dict | None:
    import json

    from huggingface_hub import hf_hub_download

    try:
        return json.loads(open(hf_hub_download(repo_id, "model_index.json", token=hf_token())).read())
    except Exception:
        return None


def _diffusers_components(repo_id: str) -> frozenset[str] | None:
    """Folder names of the pipeline components listed in model_index.json."""
    idx = _model_index(repo_id)
    if idx is None:
        return None
    return frozenset(k for k, v in idx.items() if isinstance(v, list) and v and v[0] is not None)


def _needs_image(repo_id: str) -> bool:
    """True for pipelines that animate a picture and can't start from text (judged by the pipeline class,
    since Hugging Face tags some text-to-video models like LTX-Video as image-to-video)."""
    cls = (_model_index(repo_id) or {}).get("_class_name", "")
    return "ImageToVideo" in cls or "StableVideoDiffusion" in cls or "I2V" in cls


def select_repo_files(
    files: list[dict], engine: str, components: frozenset[str] | None = None
) -> tuple[list[str], str | None]:
    """Choose a minimal, loadable set of files from a diffusers/transformers repo.

    Returns (paths, variant) where variant is "fp16" when we chose half precision weights.
    """
    paths = [f["path"] for f in files if not f["path"].lower().endswith(JUNK_EXT)]
    skip_dirs = ("onnx/", "flax/", "tf/", "openvino/", "coreml/", "original/", "assets/", ".github/")

    def is_weight(p: str) -> bool:
        return p.endswith(WEIGHT_EXT)

    keep = []
    if engine == "diffusers" and "model_index.json" in paths:
        if not components:
            components = frozenset(p.split("/")[0] for p in paths if "/" in p)
        by_dir: dict[str, list[str]] = {}
        for p in paths:
            if p.startswith(skip_dirs):
                continue
            if "/" not in p:
                # Top level: configs only. Single-file checkpoints at the root are duplicates.
                if not is_weight(p):
                    keep.append(p)
                continue
            d = p.split("/")[0]
            if d in components:
                by_dir.setdefault(d, []).append(p)
        has_fp16 = any(".fp16." in p and p.endswith(".safetensors") for p in paths)
        variant = "fp16" if has_fp16 else None
        for d, ps in by_dir.items():
            weights = [p for p in ps if is_weight(p)]
            keep.extend(p for p in ps if not is_weight(p))
            keep.extend(_pick_weights(weights, variant))
        return sorted(set(keep)), variant

    # transformers (and anything else): drop framework duplicates.
    for p in paths:
        if p.startswith(skip_dirs) or p.endswith((".gguf",)):
            continue
        keep.append(p)
    weights = [p for p in keep if is_weight(p)]
    chosen_weights = _pick_weights(weights, None)
    keep = [p for p in keep if not is_weight(p)] + chosen_weights
    return sorted(set(keep)), None


def _pick_weights(weights: list[str], variant: str | None) -> list[str]:
    st = [w for w in weights if w.endswith(".safetensors")]
    if st:
        if variant:
            v = [w for w in st if f".{variant}." in w]
            if v:
                # Also keep the shard index for the variant.
                return v
        non_variant = [w for w in st if not re.search(r"\.(fp16|fp32|bf16|non_ema|ema)\.", w)]
        return non_variant or st
    pt = [w for w in weights if w.endswith((".bin", ".pt", ".pth"))]
    if variant:
        v = [w for w in pt if f".{variant}." in w]
        if v:
            return v
    non_variant = [w for w in pt if not re.search(r"\.(fp16|fp32|bf16)\.", w)]
    return non_variant or pt
