"""Picture models that run on stable-diffusion.cpp (engines/sdcpp.py), by family.

These come as loose files rather than diffusers folders: the diffusion model (usually a GGUF, in several sizes), a text
encoder and a VAE, and for editing with a GGUF text encoder, its vision projector. Some uploads carry all of them; most
carry only the diffusion model and expect the rest from the original release.

What each file is, wanna.sh reads from the file itself, never from its name: a GGUF's header says its architecture
(general.architecture: "qwen_image21" for a Qwen-Image 2.1 diffusion model, "qwen3vl" for its text encoder, "clip" for a
vision projector), and a safetensors header lists its tensors (a VAE's encoder and decoder; a text encoder's layers,
its hidden size, and whether it carries its own vision part). Only the first few kilobytes are fetched. Names are a
fallback for when a header can't be read.

A family says which diffusion architecture is its own, which text encoder fits it, where to get the parts an upload
lacks, whether it edits, and the settings it's made for. Only families run end to end with wanna.sh belong here.
Companion files were checked to exist, and their headers read, on 2026-11-03.
"""

from __future__ import annotations

import json
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from . import hub

# Companion repo files are written "repo::path" in a download's file list (see download_worker).
SEP = "::"

QWEN_IMAGE_VAE = "Comfy-Org/Qwen-Image::split_files/vae/qwen_image_vae.safetensors"
QWEN25_VL = "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF::Qwen2.5-VL-7B-Instruct.Q8_0.gguf"
QWEN25_VL_VISION = "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF::Qwen2.5-VL-7B-Instruct.mmproj-Q8_0.gguf"
EDIT_NAME = re.compile(r"edit", re.I)
RAPID_NAME = re.compile(r"rapid", re.I)
# A model version in a file or repo name: "qwen-rapid-nsfw-v9.0-Q4_K_M.gguf", "Qwen-Image-Edit-Rapid-AIO-V19".
VERSION = re.compile(r"(?:^|[-_/ ])v(\d+(?:\.\d+)*)(?=[-_./ ]|$)", re.I)


def _version(text: str) -> tuple[int, ...]:
    """The highest version number in a name, as a tuple to compare ((9, 0) for "v9.0"), or () when there's none. Only
    the last part of a path counts: folders are named loosely ("v90/qwen-rapid-nsfw-v9.0...")."""
    found = [tuple(int(x) for x in m.group(1).split(".")) for m in VERSION.finditer(text.rsplit("/", 1)[-1])]
    return max(found, default=())


def _edit_2511(repo: str, diffusion: str = "") -> str | None:
    """Qwen-Image-Edit-2511 edits much worse without this (stable-diffusion.cpp docs/qwen_image_edit.md)."""
    return "qwen_image_zero_cond_t=true" if "2511" in repo or "2511" in diffusion else None


def _rapid_args(repo: str, diffusion: str = "") -> str | None:
    """Rapid AIO is built on Qwen-Image-Edit-2509 up to v14 and on 2511 from v15 (its model card)."""
    version = max(_version(repo), _version(diffusion))
    return "qwen_image_zero_cond_t=true" if version >= (15,) or _edit_2511(repo, diffusion) else None


FAMILIES = [
    {
        # Qwen-Image 2.1 makes pictures from a description and edits pictures you give it.
        "id": "qwen_image_2_1", "label": "Qwen-Image 2.1",
        "arch": "qwen_image21",
        "match": re.compile(r"qwen[-_ ]?image[-_ ]?2\.1", re.I),  # fallback, when no header can be read
        "makes": True, "edits": True,
        # "Up to 10 reference images" (Qwen's model card): people, products and scenes combined in one picture.
        "max_images": 10,
        # Qwen3-VL-8B: "qwen3vl" in a GGUF; hidden size 4096 in a safetensors file.
        "llm": {"arch": "qwen3vl", "hidden": 4096, "pattern": re.compile(r"qwen3[-_ ]?vl", re.I),
                "companion": "Comfy-Org/Qwen-Image-2.1::text_encoders/qwen3vl_8b_int8_convrot.safetensors"},
        # For editing with a GGUF text encoder (stable-diffusion.cpp docs/qwen_image_2.1.md). The safetensors companion
        # above carries its own vision part, so this is only fetched to go with a GGUF one.
        "vision": {"companion": "Qwen/Qwen3-VL-8B-Instruct-GGUF::mmproj-Qwen3VL-8B-Instruct-F16.gguf"},
        # Qwen-Image 2.1's own VAE: the earlier Qwen-Image one doesn't fit it (stable-diffusion.cpp's docs).
        "vae": {"companion": "Comfy-Org/Qwen-Image-2.1::vae/qwen_image_2.1_vae_bf16.safetensors"},
        # 40 steps as in Qwen's model card; guidance 6 as stable-diffusion.cpp's tested examples. Sides divisible by 32.
        "defaults": {"steps": 40, "guidance": 6.0, "width": 1024, "height": 1024},
        "sample_method": "euler", "flow_shift": None, "model_args": None,
    },
    {
        # Phr00t's Qwen-Image-Edit Rapid AIO: Qwen-Image-Edit with accelerators (Lightning) and other LoRAs merged in,
        # and its GGUF uploads (Phil2Sat's, ...). From its model card: "1 CFG, 4 step", pictures are optional ("provide
        # no images to just do pure text to image"), and euler_a/beta is the sampler most of its versions recommend
        # (v1, v4, v8, v9, v17 to v23). Listed before Qwen-Image-Edit, whose names it shares.
        "id": "qwen_image_edit_rapid", "label": "Qwen-Image-Edit Rapid",
        "arch": "qwen_image", "name_must": RAPID_NAME,
        "match": re.compile(r"qwen[-_ ]?(image[-_ ]?edit[-_ ]?)?rapid", re.I),
        "makes": True, "edits": True,
        # Qwen's recommendation for its editing models (1 to 3 pictures).
        "max_images": 3,
        "llm": {"arch": "qwen2vl", "hidden": 3584, "pattern": re.compile(r"qwen2\.?5[-_ ]?vl", re.I),
                "companion": QWEN25_VL},
        "vision": {"companion": QWEN25_VL_VISION},
        "vae": {"companion": QWEN_IMAGE_VAE},
        # Its card says 4 steps (4 to 8 for some versions); Quick never goes below that.
        "defaults": {"steps": 4, "min_steps": 4, "guidance": 1.0, "width": 1024, "height": 1024},
        "sample_method": "euler_a", "scheduler": "beta", "flow_shift": 3.0,
        "model_args": _rapid_args,
    },
    {
        # Qwen-Image-Edit, -2509 and -2511 only edit: they need a picture to start from. Their diffusion model has the
        # same architecture as Qwen-Image's ("qwen_image"), so the name (or base model) must say Edit too.
        "id": "qwen_image_edit", "label": "Qwen-Image-Edit",
        "arch": "qwen_image", "name_must": EDIT_NAME,
        "match": re.compile(r"qwen[-_ ]?image[-_ ]?edit", re.I),
        "makes": False, "edits": True,
        # 2509 added several pictures at once ("person + person", "person + scene"; best with 1 to 3, says Qwen's
        # model card) and pose maps; 2511 kept it. The original takes one picture.
        "max_images": lambda repo: 3 if re.search(r"25(09|11)", repo) else 1,
        # Qwen2.5-VL-7B: "qwen2vl" in a GGUF; hidden size 3584 in a safetensors file.
        "llm": {"arch": "qwen2vl", "hidden": 3584, "pattern": re.compile(r"qwen2\.?5[-_ ]?vl", re.I),
                "companion": QWEN25_VL},
        "vision": {"companion": QWEN25_VL_VISION},
        "vae": {"companion": QWEN_IMAGE_VAE},
        "defaults": {"steps": 40, "guidance": 2.5, "width": 1024, "height": 1024},
        "sample_method": "euler", "flow_shift": 3.0,
        "model_args": _edit_2511,
    },
]

# GGUF architectures that are a text encoder or vision projector, not a picture model. Hugging Face reports one
# architecture per repo, which may be one of these when an upload carries its text encoder too.
_NOT_DIFFUSION = {"clip"} | {f["llm"]["arch"] for f in FAMILIES}
# Uploads in these formats can't run on stable-diffusion.cpp on a PC (Apple's MLX) or need the newest cards (NVFP4);
# LoRAs, ControlNets and Turbo variants (made for other settings) aren't whole models wanna.sh can run as they are.
_SKIP_FILE = re.compile(r"(mlx|nvfp4|lora|controlnet|turbo|model_patches/)", re.I)


# --- what a file is, from its header ------------------------------------------------------------------------------

def _range(repo: str, path: str, start: int, end: int) -> bytes:
    import httpx
    from huggingface_hub import hf_hub_url

    from .config import hf_token

    headers = {"Range": f"bytes={start}-{end}"}
    if hf_token():
        headers["Authorization"] = f"Bearer {hf_token()}"
    r = httpx.get(hf_hub_url(repo, path), headers=headers, follow_redirects=True, timeout=15)
    r.raise_for_status()
    return r.content


def _gguf_arch(data: bytes) -> str | None:
    """general.architecture from the start of a GGUF file (it's the first key in every file wanna.sh has seen; a few
    more are read in case it isn't)."""
    if data[:4] != b"GGUF":
        return None
    off, kv_count = 24, struct.unpack_from("<Q", data, 16)[0]
    fixed = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}  # GGUF value types -> byte sizes
    try:
        for _ in range(min(kv_count, 16)):
            n = struct.unpack_from("<Q", data, off)[0]
            key = data[off + 8: off + 8 + n].decode()
            off += 8 + n
            vtype = struct.unpack_from("<I", data, off)[0]
            off += 4
            if vtype == 8:  # string
                n = struct.unpack_from("<Q", data, off)[0]
                value = data[off + 8: off + 8 + n].decode()
                off += 8 + n
                if key == "general.architecture":
                    return value
            elif vtype in fixed:
                off += fixed[vtype]
            else:
                return None  # an array before the architecture: give up rather than parse it all
    except (struct.error, UnicodeDecodeError):
        return None
    return None


@lru_cache(maxsize=1024)
def inspect(repo: str, path: str) -> dict | None:
    """What a model file is, read from its header: {"role": "diffusion" | "llm" | "vision" | "vae", ...} with "arch"
    (GGUF), "hidden" (a text encoder's hidden size) and "vision" (a safetensors text encoder with its vision part).
    None if it can't be read."""
    try:
        if path.endswith(".gguf"):
            arch = _gguf_arch(_range(repo, path, 0, 65535))
            if not arch:
                return None
            role = "vision" if arch == "clip" else "llm" if arch in _NOT_DIFFUSION else "diffusion"
            return {"role": role, "arch": arch}
        if path.endswith(".safetensors"):
            n = struct.unpack("<Q", _range(repo, path, 0, 7))[0]
            if n > 32 << 20:
                return None
            header = json.loads(_range(repo, path, 8, 7 + n))
            header.pop("__metadata__", None)
            names = list(header)
            if any(k.startswith(("decoder.", "encoder.")) for k in names) and \
                    not any(".layers." in k for k in names):
                return {"role": "vae"}
            emb = next((v for k, v in header.items() if k.endswith("embed_tokens.weight")), None)
            if emb:
                return {"role": "llm", "hidden": emb["shape"][-1],
                        "vision": any(k.startswith("visual.") or ".visual." in k for k in names)}
            if any(k.startswith("transformer_blocks.") for k in names):
                return {"role": "diffusion", "arch": None}
    except Exception:
        return None
    return None


def _guess(path: str, fam: dict) -> dict:
    """What a file is from its name, when its header can't be read."""
    if re.search(r"mmproj", path, re.I):
        return {"role": "vision"}
    if re.search(r"vae", path, re.I):
        return {"role": "vae"}
    if fam["llm"]["pattern"].search(path):
        llm = {"role": "llm", "arch": fam["llm"]["arch"], "hidden": fam["llm"]["hidden"]}
        # By name alone, a safetensors text encoder from Comfy-Org (the usual source) carries its vision part.
        return {**llm, "vision": path.endswith(".safetensors")}
    return {"role": "diffusion", "arch": fam["arch"]} if path.endswith(".gguf") else {"role": None}


def _candidates(files: list[dict]) -> list[dict]:
    return [f for f in files if f["path"].endswith((".gguf", ".safetensors")) and not _SKIP_FILE.search(f["path"])
            and not hub.NOT_A_MODEL_RE.search(f["path"])]


def _roles(repo: str, files: list[dict], fam: dict, read_headers: bool = True) -> dict[str, dict]:
    """What each model file in an upload is. Versions of one file that differ only in size (Q4_K_M, Q8_0...) are
    the same thing, so one header is read for each group. Without read_headers, names decide (for lists)."""
    groups: dict[tuple, list[str]] = {}
    for f in _candidates(files):
        folder, _, name = f["path"].rpartition("/")
        key = (folder, hub.QUANT_RE.sub("", name.rsplit(".", 1)[0]).lower(), name.rsplit(".", 1)[-1])
        groups.setdefault(key, []).append(f["path"])
    reps = [paths[0] for paths in groups.values()]
    found: dict[str, dict | None] = dict.fromkeys(reps)
    if read_headers:
        with ThreadPoolExecutor(6) as ex:
            found = dict(zip(reps, ex.map(lambda p: inspect(repo, p), reps)))
    out = {}
    for paths in groups.values():
        info = found[paths[0]] or _guess(paths[0], fam)
        for p in paths:
            out[p] = info
    return out


# --- families ------------------------------------------------------------------------------------------------------

def _names(repo_id: str, tags) -> list[str]:
    return [repo_id] + [t.rsplit(":", 1)[-1] for t in tags or () if t.startswith("base_model:")]


def family(repo_id: str, tags=(), arch: str | None = None) -> dict | None:
    """The family of an upload. `arch` is its diffusion model's GGUF architecture as Hugging Face reports it; with it
    the name only has to tell Qwen-Image-Edit from Qwen-Image (they share an architecture). Without it (or when the
    reported architecture is the upload's text encoder), the name or base model decides."""
    names = _names(repo_id, tags)
    if arch and arch not in _NOT_DIFFUSION:
        for fam in FAMILIES:
            if fam["arch"] == arch and (not fam.get("name_must") or any(fam["name_must"].search(n) for n in names)):
                return fam
        return None
    # The upload's own name decides first; failing that, a base_model tag ("base_model:quantized:Qwen/Qwen-Image-2.1").
    for group in ([repo_id], names[1:]):
        fam = next((f for f in FAMILIES if any(f["match"].search(n) for n in group)), None)
        if fam:
            return fam
    return None


def is_sdcpp_repo(repo_id: str, tags, siblings: list[str], arch: str | None = None) -> bool:
    """A picture upload of a known family in loose files (no diffusers folder) with at least one GGUF. Cheap: for
    lists of models. Which files are which is read from their headers when the upload is opened (variants)."""
    if "model_index.json" in siblings or family(repo_id, tags, arch) is None:
        return False
    return any(f.endswith(".gguf") and not _SKIP_FILE.search(f) for f in siblings)


def _rank(f: dict):
    """8-bit if there is one (good quality, half the size), else full precision, else the smallest."""
    name = f["path"].lower()
    eight = any(k in name for k in ("int8", "q8_0", "q8"))
    full = any(k in name for k in ("bf16", "f16", "fp16", "f32"))
    return 0 if eight else 1 if full else 2, f["size"]


def variants(repo_id: str, tags, files: list[dict], companion_size, arch: str | None = None,
             read_headers: bool = True) -> list[dict]:
    """Download choices for an upload: one per diffusion model size, each with the text encoder, VAE and vision
    projector it needs. The upload's own files are used when they fit the family (read from their headers); the rest
    come from the original release. `companion_size(ref)` gives the size of a "repo::path" file."""
    fam = family(repo_id, tags, arch)
    if fam is None:
        return []
    roles = _roles(repo_id, files, fam, read_headers)

    def by_role(role: str) -> list[dict]:
        return [f for f in files if (roles.get(f["path"]) or {}).get("role") == role]

    def fits(f: dict) -> bool:
        info = roles[f["path"]]
        if f["path"].endswith(".gguf"):
            return info.get("arch") == fam["llm"]["arch"]
        return info.get("hidden") == fam["llm"]["hidden"]

    parts: dict[str, tuple[str, int]] = {}
    own_llm = sorted((f for f in by_role("llm") if fits(f)), key=_rank)
    if own_llm:
        llm = own_llm[0]
        parts["llm"] = (llm["path"], llm["size"])
        # A text encoder without its vision part needs the projector made for it: the upload's own.
        needs_vision = fam["edits"] and not roles[llm["path"]].get("vision")
        own_vision = sorted(by_role("vision"), key=_rank)
        if needs_vision and own_vision:
            parts["vision"] = (own_vision[0]["path"], own_vision[0]["size"])
        elif needs_vision:
            parts["vision"] = (fam["vision"]["companion"], companion_size(fam["vision"]["companion"]))
    else:
        # The original release's text encoder, and its projector when it's a GGUF (the safetensors ones carry theirs).
        ref = fam["llm"]["companion"]
        parts["llm"] = (ref, companion_size(ref))
        if fam["edits"] and ref.endswith(".gguf"):
            parts["vision"] = (fam["vision"]["companion"], companion_size(fam["vision"]["companion"]))
    own_vae = sorted(by_role("vae"), key=_rank)
    if own_vae:
        parts["vae"] = (own_vae[0]["path"], own_vae[0]["size"])
    else:
        parts["vae"] = (fam["vae"]["companion"], companion_size(fam["vae"]["companion"]))

    models = [f for f in by_role("diffusion") if f["path"].endswith(".gguf")
              # single-file safetensors models aren't offered yet; another family's model isn't this one
              and not (roles[f["path"]].get("arch") and roles[f["path"]]["arch"] != fam["arch"])]
    # Some uploads carry several versions of the model, each in many sizes (Rapid AIO v5.0 to v9.0, 14 sizes each).
    # Offer the newest version's sizes, labelled with the version, rather than a long mixed list.
    stems = {_stem(f["path"]) for f in models}
    newest = None
    if len(stems) > 1 and any(_version(s) for s in stems):
        newest = max(stems, key=lambda s: (_version(s), s))
        models = [f for f in models if _stem(f["path"]) == newest]

    out = []
    for f in models:
        m = hub.QUANT_RE.search(f["path"].rsplit("/", 1)[-1].removesuffix(".gguf"))
        quant = m.group(1).upper() if m else None
        tier = hub._tier(quant)
        components = {"diffusion": f["path"], **{k: v[0] for k, v in parts.items()}}
        extra = sum(v[1] or 0 for v in parts.values())
        version = ".".join(map(str, _version(newest))) if newest else ""
        out.append({
            "id": f["path"], "quant": quant,
            "label": (f"v{version} " if version else "") + tier["label"] + (f" ({quant})" if quant else ""),
            "description": tier["description"], "rank": tier["rank"],
            "files": [f["path"], *(v[0] for v in parts.values())],
            "size": f["size"] + extra,
            "model_size": f["size"],
            # Graphics memory while drawing: the diffusion model and VAE. The text encoder runs once per picture and
            # can sit in system memory.
            "weights": f["size"] + (parts["vae"][1] or 0),
            "encoder_size": (parts["llm"][1] or 0) + (parts.get("vision", (None, 0))[1] or 0),
            "components": components,
        })
    if len(out) > 2:
        # Full precision copies of these models are 40 GB and up; offer them, but rank like the rest.
        sizes = sorted(v["model_size"] for v in out)
        median = sizes[len(sizes) // 2]
        out = [v for v in out if v["model_size"] >= median * 0.25]
    out.sort(key=lambda v: (v["rank"], v["size"]))
    return out


def _stem(path: str) -> str:
    """A model file's name without its size ("v90/qwen-rapid-nsfw-v9.0" for "v90/qwen-rapid-nsfw-v9.0-Q4_K_M.gguf")."""
    folder, _, name = path.rpartition("/")
    stem = hub.QUANT_RE.sub("", name.rsplit(".", 1)[0])
    return f"{folder}/{stem}" if folder else stem


def settings(model: dict) -> dict:
    """What the worker needs to load an installed model: its family's sampler, scheduler, flow shift and model
    arguments (some depend on which file was downloaded, such as a Rapid AIO version)."""
    meta = (model.get("meta") or {}).get("sdcpp") or {}
    fam = by_id(meta.get("family"))
    if fam is None:
        return {}
    diffusion = (meta.get("parts") or {}).get("diffusion", "")
    args = fam["model_args"](model["repo_id"], diffusion) if callable(fam["model_args"]) else fam["model_args"]
    return {"sample_method": fam["sample_method"], "scheduler": fam.get("scheduler"), "flow_shift": fam["flow_shift"],
            "model_args": args}


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
