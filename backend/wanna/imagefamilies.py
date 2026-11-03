"""Picture models that run on stable-diffusion.cpp (engines/sdcpp.py), by family.

These come as loose files rather than diffusers folders: the diffusion model (usually a GGUF, in several sizes), a text
encoder and a VAE. Some uploads carry all three; most carry only the diffusion model and expect the others from the
original release. A family says how to recognise its uploads, which companion files it needs and where to get them when
an upload doesn't have them, whether it edits pictures, and the settings it's made for.

Only families run end to end with wanna.sh belong here. Companion files were checked to exist on 2026-11-03.
"""

from __future__ import annotations

import re

from . import hub

# Companion repo files are written "repo::path" in a download's file list (see download_worker).
SEP = "::"

QWEN_IMAGE_VAE = "Comfy-Org/Qwen-Image::split_files/vae/qwen_image_vae.safetensors"
QWEN25_VL = "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF::Qwen2.5-VL-7B-Instruct.Q8_0.gguf"
QWEN25_VL_VISION = "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF::Qwen2.5-VL-7B-Instruct.mmproj-Q8_0.gguf"

FAMILIES = [
    {
        # Qwen-Image 2.1 makes pictures from a description and edits pictures you give it.
        "id": "qwen_image_2_1", "label": "Qwen-Image 2.1",
        "match": re.compile(r"qwen[-_ ]?image[-_ ]?2\.1", re.I),
        "makes": True, "edits": True,
        # "Up to 10 reference images" (Qwen's model card): people, products and scenes combined in one picture.
        "max_images": 10,
        "llm": {"pattern": re.compile(r"qwen3[-_ ]?vl", re.I),
                "companion": "Comfy-Org/Qwen-Image-2.1::text_encoders/qwen3vl_8b_int8_convrot.safetensors"},
        # Editing needs the text encoder's vision part. Safetensors text encoders include it; a GGUF one needs its
        # projector beside it (stable-diffusion.cpp docs/qwen_image_2.1.md), from the upload or from Qwen's release.
        "vision": {"pattern": re.compile(r"mmproj", re.I),
                   "companion": "Qwen/Qwen3-VL-8B-Instruct-GGUF::mmproj-Qwen3VL-8B-Instruct-F16.gguf"},
        "vae": {"pattern": re.compile(r"vae", re.I),
                "companion": "Comfy-Org/Qwen-Image-2.1::vae/qwen_image_2.1_vae_bf16.safetensors"},
        # 40 steps as in Qwen's model card; guidance 6 as stable-diffusion.cpp's tested examples. Sides divisible by 32.
        "defaults": {"steps": 40, "guidance": 6.0, "width": 1024, "height": 1024},
        "sample_method": "euler", "flow_shift": None, "model_args": None,
    },
    {
        # Qwen-Image-Edit, -2509 and -2511 only edit: they need a picture to start from.
        "id": "qwen_image_edit", "label": "Qwen-Image-Edit",
        "match": re.compile(r"qwen[-_ ]?image[-_ ]?edit", re.I),
        "makes": False, "edits": True,
        # 2509 added several pictures at once ("person + person", "person + scene"; best with 1 to 3, says Qwen's
        # model card) and pose maps; 2511 kept it. The original takes one picture.
        "max_images": lambda repo: 3 if re.search(r"25(09|11)", repo) else 1,
        "llm": {"pattern": re.compile(r"qwen2\.?5[-_ ]?vl", re.I), "companion": QWEN25_VL},
        "vision": {"pattern": re.compile(r"mmproj", re.I), "companion": QWEN25_VL_VISION},
        "vae": {"pattern": re.compile(r"vae", re.I), "companion": QWEN_IMAGE_VAE},
        "defaults": {"steps": 40, "guidance": 2.5, "width": 1024, "height": 1024},
        "sample_method": "euler", "flow_shift": 3.0,
        # 2511 edits much worse without this (stable-diffusion.cpp docs/qwen_image_edit.md).
        "model_args": lambda repo: "qwen_image_zero_cond_t=true" if "2511" in repo else None,
    },
]

# Uploads in these formats can't run on stable-diffusion.cpp on a PC (Apple's MLX) or need the newest cards (NVFP4).
_SKIP_FILE = re.compile(r"(mlx|nvfp4|lora|controlnet|turbo|model_patches/)", re.I)
# A vision projector is named after its language model too ("Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf").
_PROJECTOR = re.compile(r"mmproj", re.I)


def family(repo_id: str, tags=()) -> dict | None:
    """The family of an upload, from its name or the model it was made from (its base_model tags)."""
    # The upload's own name decides first; failing that, a base_model tag ("base_model:quantized:Qwen/Qwen-Image-2.1").
    bases = [t.rsplit(":", 1)[-1] for t in tags or () if t.startswith("base_model:")]
    for names in ([repo_id], bases):
        fam = next((f for f in FAMILIES if any(f["match"].search(n) for n in names)), None)
        if fam:
            return fam
    return None


def is_sdcpp_repo(repo_id: str, tags, siblings: list[str]) -> bool:
    """A picture upload of a known family in loose files (no diffusers folder) with at least one GGUF diffusion model."""
    if "model_index.json" in siblings or family(repo_id, tags) is None:
        return False
    return any(_is_diffusion(f, family(repo_id, tags)) for f in siblings)


def _is_diffusion(path: str, fam: dict) -> bool:
    if not path.endswith(".gguf") or _SKIP_FILE.search(path) or hub.NOT_A_MODEL_RE.search(path):
        return False
    return not any(fam[k] and fam[k]["pattern"].search(path) for k in ("llm", "vision", "vae"))


def _pick(files: list[dict], spec: dict | None, ext=(".safetensors", ".gguf")) -> dict | None:
    """The best in-repo file for a companion part: 8-bit if there is one (good quality, half the size), else the
    smallest of at least 8 bits, else the smallest."""
    if not spec:
        return None
    cands = [f for f in files if f["path"].endswith(ext) and spec["pattern"].search(f["path"])
             and not _SKIP_FILE.search(f["path"])]
    if not cands:
        return None

    def rank(f):
        name = f["path"].lower()
        eight = any(k in name for k in ("int8", "q8_0", "q8"))
        full = any(k in name for k in ("bf16", "f16", "fp16", "f32"))
        return (0 if eight else 1 if full else 2, f["size"])

    return sorted(cands, key=rank)[0]


def variants(repo_id: str, tags, files: list[dict], companion_size) -> list[dict]:
    """Download choices for an upload: one per diffusion model size, each with the text encoder, VAE and (for editing
    with a GGUF text encoder) vision projector it needs. `companion_size(ref)` gives the size of a "repo::path" file."""
    fam = family(repo_id, tags)
    if fam is None:
        return []
    parts = {}
    for key in ("llm", "vision", "vae"):
        spec = fam[key]
        if not spec:
            continue
        pool = files if key == "vision" else [f for f in files if not _PROJECTOR.search(f["path"])]
        found = _pick(pool, spec, (".gguf",) if key == "vision" else (".safetensors", ".gguf"))
        if found:
            parts[key] = (found["path"], found["size"])
        else:
            parts[key] = (spec["companion"], companion_size(spec["companion"]))
    # A safetensors text encoder brings its own vision weights; the projector is only for a GGUF one.
    if "vision" in parts and not parts["llm"][0].endswith(".gguf"):
        parts.pop("vision")

    out = []
    for f in files:
        if not _is_diffusion(f["path"], fam):
            continue
        m = hub.QUANT_RE.search(f["path"].rsplit("/", 1)[-1].removesuffix(".gguf"))
        quant = m.group(1).upper() if m else None
        tier = hub._tier(quant)
        components = {"diffusion": f["path"], **{k: v[0] for k, v in parts.items()}}
        extra = sum(v[1] or 0 for v in parts.values())
        out.append({
            "id": f["path"], "quant": quant,
            "label": tier["label"] + (f" ({quant})" if quant else ""),
            "description": tier["description"], "rank": tier["rank"],
            "files": [f["path"], *(v[0] for v in parts.values())],
            "size": f["size"] + extra,
            "model_size": f["size"],
            # Graphics memory while drawing: the diffusion model and VAE. The text encoder runs once per picture and
            # can sit in system memory.
            "weights": f["size"] + (parts.get("vae", (None, 0))[1] or 0),
            "encoder_size": (parts.get("llm", (None, 0))[1] or 0) + (parts.get("vision", (None, 0))[1] or 0),
            "components": components,
        })
    if len(out) > 2:
        # Full precision copies of these models are 40 GB and up; offer them, but rank like the rest.
        sizes = sorted(v["model_size"] for v in out)
        median = sizes[len(sizes) // 2]
        out = [v for v in out if v["model_size"] >= median * 0.25]
    out.sort(key=lambda v: (v["rank"], v["size"]))
    return out


def settings(model: dict) -> dict:
    """What the worker needs to load an installed model: its family's sampler, flow shift and model arguments."""
    meta = (model.get("meta") or {}).get("sdcpp") or {}
    fam = next((f for f in FAMILIES if f["id"] == meta.get("family")), None)
    if fam is None:
        return {}
    args = fam["model_args"](model["repo_id"]) if callable(fam["model_args"]) else fam["model_args"]
    return {"sample_method": fam["sample_method"], "flow_shift": fam["flow_shift"], "model_args": args}


def by_id(family_id: str | None) -> dict | None:
    return next((f for f in FAMILIES if f["id"] == family_id), None)


def max_images(model: dict) -> int:
    """How many pictures a picture model can take at once: several for models that combine them (Qwen-Image 2.1,
    Qwen-Image-Edit-2509 and -2511), one for the rest (other editing models, and diffusers models redrawing a
    starting picture). `model` is an installed model, or hub details ({"repo_id", "family"})."""
    family_id = model.get("family") or ((model.get("meta") or {}).get("sdcpp") or {}).get("family")
    fam = by_id(family_id)
    if fam is None:
        return 1
    limit = fam["max_images"]
    return limit(model["repo_id"]) if callable(limit) else limit


def too_many_pictures(model: dict, count: int) -> str | None:
    """Why `count` pictures are too many for this installed model, naming installed models that take that many, or
    None when it can take them."""
    limit = max_images(model)
    if count <= limit:
        return None
    from . import db

    name = (model.get("meta") or {}).get("title") or model["id"]
    more = [(m.get("meta") or {}).get("title") or m["id"] for m in db.list_models()
            if m["task"] == "image" and max_images(m) >= count]
    most = max(f["max_images"]("2511") if callable(f["max_images"]) else f["max_images"] for f in FAMILIES)
    if more:
        hint = f" These installed models can: {', '.join(more)}."
    elif count > most:
        hint = f" No picture model takes more than {most} at once."
    else:
        hint = (" Models that combine several pictures, such as Qwen-Image 2.1 (up to 10) or Qwen-Image-Edit-2511 "
                "(up to 3), are in Get models → Pictures.")
    takes = "one picture" if limit == 1 else f"up to {limit} pictures"
    return f"{name} takes {takes} at once; {count} were attached.{hint}"
