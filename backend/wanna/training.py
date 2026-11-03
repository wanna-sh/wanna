"""Training LoRAs: for picture models, your own subject (a person, a pet, a product) or style, from a few pictures;
for chat models, your writing voice or how to answer, from your writing or example chats.

Each training run is a folder in ~/.wanna/training/<id>: run.json (what to train), status.json (how it went), the
examples (pictures/ or data/), the result (lora/ for pictures, lora.gguf for chat) and samples/. The work happens in its
own process (workers/train.py or workers/train_chat.py); this module starts it, follows its progress and keeps the list.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import db, gpu
from .config import HOME, MODELS_DIR

log = logging.getLogger("wanna.training")

TRAIN_DIR = HOME / "training"
MAX_PICTURES = 50
MIN_PICTURES = 3
# Graphics memory a run needs, and seconds per training step, measured on an RTX 3060 12 GB with nothing else
# running on it (rank 16, gradient checkpointing, bfloat16): SD 1.5 at 512 px, 0.45 s a step, peaking at 3.4 GB;
# SDXL at 1024 px, 1.8 s a step, peaking at 9.8 GB while making the sample pictures at the end (7.7 GB while
# training). Room is left for the driver.
NEEDS = {"sd": 5 * 1024**3, "sdxl": 11 * 1024**3}
SECONDS_PER_STEP = {"sd": 0.45, "sdxl": 1.8}
MEASURED_BANDWIDTH = 360e9  # the RTX 3060's memory bandwidth; other cards are estimated in proportion
RESOLUTION = {"sd": 512, "sdxl": 1024}
PICTURE = re.compile(r"\.(png|jpe?g|webp|bmp|gif)$", re.I)
TRIGGER = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,23}$")

ACTIVE = ("queued", "downloading", "preparing", "training", "saving", "samples")

_lock = threading.Lock()
_procs: dict[str, subprocess.Popen] = {}


class TrainError(Exception):
    """A problem to show the person, with what to do about it."""


def kind_of(model: dict) -> str | None:
    from .workers.train import kind_of as _kind

    return _kind(model["path"]) if model.get("task") == "image" else None


def ready() -> dict:
    """Whether this computer can train: the AI libraries with PEFT, and an NVIDIA graphics card."""
    if importlib.util.find_spec("torch") is None or importlib.util.find_spec("diffusers") is None:
        return {"ok": False, "missing": "ml", "reason": "Training needs the AI libraries for pictures. Install them "
                "first (a one-time download)."}
    if importlib.util.find_spec("peft") is None:
        return {"ok": False, "missing": "peft", "reason": "Training needs one more library (PEFT), added after your "
                "AI libraries were installed. Install it: a small download."}
    cards = [g for g in gpu.list_gpus() if g.get("uuid") != "apple-gpu"]
    if not cards:
        return {"ok": False, "missing": "gpu", "reason": "Training needs an NVIDIA graphics card. Macs and computers "
                "without one can use trained styles, but not train them yet."}
    return {"ok": True, "missing": None, "reason": None}


def models() -> list[dict]:
    """Installed picture models that can be trained: how much graphics memory each needs, whether a card here has
    it, and about how long a training step takes on that card."""
    cards = [g for g in gpu.list_gpus() if g.get("uuid") != "apple-gpu"]
    out = []
    for m in db.list_models():
        kind = kind_of(m)
        if not kind:
            continue
        fits = [g for g in cards if g["memory_total"] >= NEEDS[kind] * 0.9]
        card = max(fits, key=lambda g: g["memory_total"], default=None)
        bw = gpu.memory_bandwidth(card["index"]) if card else None
        out.append({"id": m["id"], "repo_id": m["repo_id"], "title": (m.get("meta") or {}).get("title") or m["id"],
                    "kind": kind, "needs": NEEDS[kind], "resolution": RESOLUTION[kind],
                    "card": card["name"] if card else None,
                    "seconds_per_step": round(SECONDS_PER_STEP[kind] * MEASURED_BANDWIDTH / bw, 2) if bw else None})
    return out


def defaults(preset: str, pictures: int) -> dict:
    """Settings that work for most runs. Steps grow with the number of pictures, within limits."""
    if preset == "style":
        steps = min(2000, max(600, 100 * pictures))
    else:
        steps = min(1500, max(400, 80 * pictures))
    return {"steps": steps, "rank": 16, "learning_rate": 1e-4}


# --- runs ------------------------------------------------------------------------------------------------------------

def _folder(rid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", rid or ""):
        raise TrainError("There's no training run with that id.")
    return TRAIN_DIR / rid


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _status(rid: str, **patch) -> dict:
    p = _folder(rid) / "status.json"
    with _lock:
        status = {**_read(p), **patch, "updated": time.time()}
        p.write_text(json.dumps(status))
    return status


def get(rid: str) -> dict:
    folder = _folder(rid)
    run = _read(folder / "run.json")
    if not run:
        raise TrainError("There's no training run with that id.")
    status = _read(folder / "status.json")
    if status.get("stage") in ACTIVE and rid not in _procs:
        status = {**status, "stage": "interrupted", "message": "Stopped when wanna.sh closed. Start it again."}
    out = {
        "id": rid, "type": run.get("type", "picture"), "name": run["name"], "preset": run["preset"],
        "trigger": run["trigger"], "what": run.get("what", ""), "model": run["model"],
        "model_title": run.get("model_title"), "kind": run["kind"], "steps": run["steps"], "created": run["created"],
        "status": status,
    }
    if out["type"] == "chat":
        replies = _read(folder / "samples" / "replies.json") if (folder / "samples" / "replies.json").exists() else []
        registered = run.get("registered") if run.get("registered") and db.get_model(run["registered"]) else None
        return {**out, "examples": run.get("examples"), "mode": run.get("mode"), "original": run.get("original_repo"),
                "ready": bool(registered) and status.get("stage") == "done", "chat_model": registered,
                "replies": replies if isinstance(replies, list) else []}
    samples = sorted((folder / "samples").glob("*.png")) if (folder / "samples").exists() else []
    return {
        **out, "pictures": len(list((folder / "pictures").iterdir())) if (folder / "pictures").exists() else 0,
        "ready": (folder / "lora" / "pytorch_lora_weights.safetensors").exists() and status.get("stage") == "done",
        "samples": [f"/api/training/{rid}/samples/{p.name}" for p in samples],
        "prompt": example_prompt(run),
    }


def list_runs() -> list[dict]:
    TRAIN_DIR.mkdir(exist_ok=True)
    out = []
    for p in TRAIN_DIR.iterdir():
        if p.is_dir() and (p / "run.json").exists():
            try:
                out.append(get(p.name))
            except TrainError:
                continue
    return sorted(out, key=lambda r: -r["created"])


def example_prompt(run: dict) -> str:
    """A prompt that uses the trained word, to start from on the Pictures page."""
    if run["preset"] == "style":
        return f"a lighthouse on a cliff at sunset, in the style of {run['trigger']}"
    return f"a photo of {run['trigger']} {run.get('what') or ''}".strip() + " on a beach"


def create(model_id: str, preset: str, name: str, trigger: str, what: str, pictures: list[tuple[str, bytes]],
           steps: int | None = None) -> dict:
    """Check everything, save the pictures, and start training."""
    state = ready()
    if not state["ok"]:
        raise TrainError(state["reason"])
    model = db.get_model(model_id)
    kind = kind_of(model) if model else None
    if not kind:
        raise TrainError("Choose an installed Stable Diffusion 1.5 or SDXL picture model to train.")
    if preset not in ("subject", "style"):
        raise TrainError("Choose what to teach it: a subject or a style.")
    if not TRIGGER.match(trigger or ""):
        raise TrainError("The trigger word is one made-up word you'll put in prompts, like zwx or myrex: 3 to 24 "
                         "letters and digits, starting with a letter.")
    pictures = [(n, d) for n, d in pictures if PICTURE.search(n)]
    if not MIN_PICTURES <= len(pictures) <= MAX_PICTURES:
        raise TrainError(f"Add {MIN_PICTURES} to {MAX_PICTURES} pictures (PNG, JPEG or WebP). 10 to 20 varied ones "
                         "work best.")
    if any(r["status"].get("stage") in ACTIVE for r in list_runs()):
        raise TrainError("Another training run is going. Wait for it to finish, or stop it first.")
    rid = uuid.uuid4().hex[:12]
    folder = TRAIN_DIR / rid
    (folder / "pictures").mkdir(parents=True)
    for n, (filename, data) in enumerate(pictures, 1):
        (folder / "pictures" / f"{n:03d}{Path(filename).suffix.lower()}").write_bytes(data)
    d = defaults(preset, len(pictures))
    run = {
        "name": (name or "").strip()[:80] or trigger, "preset": preset, "trigger": trigger,
        "what": (what or "").strip()[:60], "model": model["id"], "model_title": (model.get("meta") or {}).get("title"),
        "repo_id": model["repo_id"], "model_path": model["path"], "variant": (model.get("meta") or {}).get("variant"),
        "kind": kind, "resolution": RESOLUTION[kind], "rank": d["rank"], "learning_rate": d["learning_rate"],
        "steps": max(100, min(4000, int(steps))) if steps else d["steps"], "created": time.time(),
    }
    run["sample_prompts"] = [example_prompt(run), *(
        [f"a portrait photo of {trigger} {run['what']}".strip(), f"a watercolor painting of {trigger} {run['what']}".strip()]
        if preset == "subject" else [f"a city street at night, in the style of {trigger}",
                                     f"a bowl of fruit on a table, in the style of {trigger}"])]
    (folder / "run.json").write_text(json.dumps(run, indent=2))
    _status(rid, stage="queued", message="Starting")
    try:
        _start(rid, run)
    except TrainError as e:
        _status(rid, stage="error", message=str(e))
    return get(rid)


def _pick_card(kind: str) -> int:
    """The card to train on: the one with the most free memory, after stopping wanna.sh's models on it if needed."""
    from .workers.manager import manager

    need = NEEDS[kind]
    cards = [g for g in gpu.list_gpus() if g["memory_total"] >= need * 0.9]
    if not cards:
        biggest = max((g["memory_total"] for g in gpu.list_gpus()), default=0)
        raise TrainError(f"Training this model needs a graphics card with about {need / 1024**3:.0f} GB; the biggest "
                         f"here has {biggest / 1024**3:.0f} GB."
                         + (" Train a Stable Diffusion 1.5 model instead." if kind == "sdxl" else ""))
    card = max(cards, key=lambda g: g["memory_free"])
    if card["memory_free"] < need:
        for w in manager.loaded():
            if card["index"] in w["gpus"]:
                manager.unload(w["id"])
                manager._log(f"Stopped {w['id']} to make room for training")
        time.sleep(2)
        card = next(g for g in gpu.list_gpus() if g["index"] == card["index"])
    if card["memory_free"] < need * 0.9:
        raise TrainError(f"Training needs about {need / 1024**3:.0f} GB free on one graphics card; "
                         f"{card['name']} has {card['memory_free'] / 1024**3:.1f} GB free. Close other programs that "
                         "use it (games, other AI apps) and try again.")
    return card["index"]


def _start(rid: str, run: dict) -> None:
    chat = run.get("type") == "chat"
    if chat:
        billions = (run.get("original_bytes") or 0) / 2 / 1e9  # the original is stored at 16 bits a parameter
        cards = _free_cards(run["cards"], CHAT_NEEDS[run["mode"]](billions) / len(run["cards"]))
        _install_converter(run["llama_tag"])
    else:
        cards = [_pick_card(run["kind"])]
    folder = _folder(rid)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": ",".join(map(str, cards)), "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
           "PYTHONUNBUFFERED": "1", "WANNA_SERVER_PID": str(os.getpid()),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    if chat:  # downloads the original weights the first time
        from .config import hf_token

        env.pop("HF_HUB_OFFLINE", None)
        if hf_token():
            env["HF_TOKEN"] = hf_token()
    else:
        env["HF_HUB_OFFLINE"] = "1"
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    (folder / "stop").unlink(missing_ok=True)
    log_file = open(folder / "train.log", "w")
    worker = "wanna.workers.train_chat" if chat else "wanna.workers.train"
    proc = subprocess.Popen([sys.executable, "-m", worker, str(folder)], stdout=subprocess.PIPE,
                            stderr=log_file, text=True, env=env, **kwargs)
    _procs[rid] = proc
    _status(rid, stage="preparing", message="Starting", gpu=cards[0], gpus=cards, started=time.time(), pid=proc.pid)
    threading.Thread(target=_follow, args=(rid, proc, log_file), daemon=True, name=f"train-{rid}").start()
    log.info("Training %s (%s) on GPU %s", rid, run["name"], cards)


def _free_cards(cards: list[int], need_each: float) -> list[int]:
    """Make room on the cards a chat run trains on: stop wanna.sh's models there if a card is short of memory."""
    from .workers.manager import manager

    here = {g["index"]: g for g in gpu.list_gpus()}
    if any(here.get(i, {}).get("memory_free", 0) < need_each for i in cards):
        for w in manager.loaded():
            if set(w["gpus"]) & set(cards):
                manager.unload(w["id"])
                manager._log(f"Stopped {w['id']} to make room for training")
        time.sleep(2)
        here = {g["index"]: g for g in gpu.list_gpus()}
    short = [here[i] for i in cards if i in here and here[i]["memory_free"] < need_each * 0.9]
    if short:
        raise TrainError(f"Training needs about {need_each / 1e9:.0f} GB free on {short[0]['name']}, which has "
                         f"{short[0]['memory_free'] / 1e9:.1f} GB free. Close other programs that use it (games, "
                         "other AI apps) and try again.")
    return cards


def _install_converter(tag: str) -> None:
    """llama.cpp's convert_lora_to_gguf.py and what it needs, from the same release as the chat engine, fetched once
    (about 40 MB to download; a few MB kept)."""
    import io
    import zipfile

    import httpx

    dest = CONVERTER_DIR / tag
    if (dest / "convert_lora_to_gguf.py").exists():
        return
    try:
        r = httpx.get(f"https://github.com/ggml-org/llama.cpp/archive/refs/tags/{tag}.zip", follow_redirects=True,
                      timeout=300)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise TrainError(f"Couldn't download llama.cpp's converter ({e}). Check the internet connection.") from None
    keep = ("convert_lora_to_gguf.py", "convert_hf_to_gguf.py", "conversion/", "gguf-py/gguf/")
    tmp = dest.with_name(dest.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            rel = name.split("/", 1)[1] if "/" in name else ""
            if rel and not name.endswith("/") and rel.startswith(keep):
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp / rel).write_bytes(z.read(name))
    if not (tmp / "convert_lora_to_gguf.py").exists():
        raise TrainError("llama.cpp's converter wasn't where expected in its download.")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)


def _follow(rid: str, proc: subprocess.Popen, log_file) -> None:
    """Keep status.json up to date from the trainer's progress lines."""
    last = None
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        last = msg
        if msg.get("stage") == "done" and _read(_folder(rid) / "run.json").get("type") == "chat":
            _register(rid, msg.get("gguf"))
        _status(rid, **msg)
    code = proc.wait()
    log_file.close()
    if _procs.pop(rid, None) is None:
        return  # shutdown() stopped it
    if code != 0 and (not last or last.get("stage") not in ("error", "stopped")):
        _status(rid, stage="error", message=_tail(_folder(rid) / "train.log"))


def _tail(path: Path) -> str:
    try:
        lines = [x for x in path.read_text(errors="replace").splitlines() if x.strip()]
    except OSError:
        return "Training stopped unexpectedly."
    return (lines[-1] if lines else "Training stopped unexpectedly.")[-400:]


def shutdown() -> None:
    """Stop training when wanna.sh stops: nothing would follow it, and it would keep its graphics card busy."""
    for rid, proc in list(_procs.items()):
        _procs.pop(rid, None)
        proc.kill()
        proc.wait()
        _status(rid, stage="interrupted", message="Stopped when wanna.sh closed. Start it again.")


def stop_leftovers() -> None:
    """At start: stop trainers left running by a wanna.sh that didn't close cleanly."""
    import psutil

    for run in list_runs():
        pid = run["status"].get("pid")
        if run["status"].get("stage") != "interrupted" or not pid:
            continue
        try:
            p = psutil.Process(pid)
            if "wanna.workers.train" in " ".join(p.cmdline()):
                p.kill()
                log.info("Stopped a leftover training run (%s)", run["name"])
        except psutil.Error:
            pass


def stop(rid: str) -> dict:
    """Ask a run to stop after its current step; force it if it hasn't within half a minute."""
    folder = _folder(rid)
    (folder / "stop").touch()
    proc = _procs.get(rid)
    if proc:
        def force():
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                _status(rid, stage="stopped", message="Stopped")
        threading.Thread(target=force, daemon=True).start()
    else:
        _status(rid, stage="stopped", message="Stopped")
    return get(rid)


def restart(rid: str) -> dict:
    """Train an interrupted, stopped or failed run again from the start, with the same pictures and settings."""
    run = _read(_folder(rid) / "run.json")
    if rid in _procs:
        raise TrainError("It's already training.")
    if run.get("type") == "chat":
        _unregister(rid)
        (_folder(rid) / "lora.gguf").unlink(missing_ok=True)
        shutil.rmtree(_folder(rid) / "adapter", ignore_errors=True)
    shutil.rmtree(_folder(rid) / "lora", ignore_errors=True)
    shutil.rmtree(_folder(rid) / "samples", ignore_errors=True)
    _status(rid, stage="queued", message="Starting", step=0)
    try:
        _start(rid, run)
    except TrainError as e:
        _status(rid, stage="error", message=str(e))
    return get(rid)


def delete(rid: str) -> None:
    folder = _folder(rid)
    if rid in _procs:
        raise TrainError("Stop the training first.")
    run = _read(folder / "run.json")
    _unregister(rid)
    shutil.rmtree(folder, ignore_errors=True)
    matched = run.get("matched_path")
    if matched and not any(_read(p / "run.json").get("matched_path") == matched
                           for p in TRAIN_DIR.iterdir() if p.is_dir()):
        Path(matched).unlink(missing_ok=True)  # no other trained model runs on it


def rename(rid: str, name: str) -> dict:
    p = _folder(rid) / "run.json"
    run = _read(p)
    run["name"] = name.strip()[:80] or run["name"]
    p.write_text(json.dumps(run, indent=2))
    if run.get("registered"):
        db.update_model_meta(run["registered"], {"title": f"{run['name']} ({run.get('model_title') or run['model']})"})
    return get(rid)


# --- using a trained style -------------------------------------------------------------------------------------------

def for_model(model: dict) -> list[dict]:
    """Finished styles that work with this picture model: ones trained on the same model (by its Hugging Face repo)."""
    return [{"id": r["id"], "name": r["name"], "trigger": r["trigger"], "prompt": r["prompt"]}
            for r in list_runs() if r["type"] == "picture" and r["ready"]
            and _read(_folder(r["id"]) / "run.json").get("repo_id") == model["repo_id"]]


def apply(model: dict, params: dict) -> dict:
    """Turn a request's "lora" (a trained style's id) and "lora_strength" into the worker's lora_path. Paths from
    clients are never used."""
    params.pop("lora_path", None)
    rid = params.pop("lora", None)
    strength = params.pop("lora_strength", None)
    if not rid:
        return params
    usable = {r["id"] for r in for_model(model)}
    if rid not in usable:
        raise TrainError("That trained style isn't finished, was deleted, or was trained on a different picture model.")
    try:
        strength = float(strength if strength is not None else 1.0)
    except (TypeError, ValueError):
        raise TrainError("lora_strength should be a number from 0 to 1.5.") from None
    params["lora_path"] = str(_folder(rid) / "lora")
    params["lora_strength"] = max(0.0, min(1.5, strength))
    return params


# --- chat models -----------------------------------------------------------------------------------------------------
#
# Chat models run in llama.cpp from GGUF files, which can't be trained. A chat run trains on the model's original
# weights (found from the GGUF's model card, downloaded once into models/originals/) and turns the LoRA into a llama.cpp
# adapter, lora.gguf, which runs on top of the GGUF model already installed. The finished run is added to the installed
# models as a chat model of its own (the same GGUF, with --lora), so Chat, Code and any app pick it by name.

ORIGINALS_DIR = MODELS_DIR / "originals"  # the weights training starts from: free to delete, downloaded again if needed
MATCHED_DIR = MODELS_DIR / "matched"  # the GGUF copies trained chat models run on (workers/train_chat.matching_gguf)
CONVERTER_DIR = HOME / "engines" / "llama-convert"
MIRRORS = ("unsloth",)  # ungated copies of gated originals (same weights), used when the original can't be downloaded
CHAT_PRESETS = ("voice", "chats")
MIN_WORDS, MIN_CHATS, MAX_CHATS = 300, 10, 5000
GB = 1e9
# Measured on the RTX 3060 12 GB (rank 16 on every attention and feed-forward layer, gradient checkpointing): Llama 3.2
# 1B at bfloat16 peaked at 2.8 GB; Qwen3 8B in 4 bits at 7.1 GB. About 1 s per example for the 8B, 0.55 s for the 1B.
CHAT_NEEDS = {"bf16": lambda b: (2.1 * b + 0.6) * GB, "4bit": lambda b: (0.75 * b + 1.0) * GB}


def _billions(original: dict) -> float:
    return (original.get("params") or 0) / 1e9


def original_for(model: dict) -> dict:
    """The original (trainable) weights behind an installed GGUF chat model, from its model card's base_model:
    {"repo", "params", "bytes", "architecture"} or {"error": why not}. Remembered for a week."""
    cache_path = TRAIN_DIR / "originals.json"
    cache = _read(cache_path)
    hit = cache.get(model["repo_id"])
    if hit and time.time() - hit.get("checked", 0) < 7 * 86400:
        return hit
    try:
        found = _find_original(model["repo_id"])
    except Exception as e:  # offline, or the Hub is down: say so, but don't remember it
        return {"error": f"Couldn't look up the original model on Hugging Face ({type(e).__name__}). Check the "
                         "internet connection."}
    found["checked"] = time.time()
    TRAIN_DIR.mkdir(exist_ok=True)
    cache[model["repo_id"]] = found
    cache_path.write_text(json.dumps(cache, indent=2))
    return found


def _find_original(repo_id: str) -> dict:
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    from . import hub

    api = hub.api()
    repo = repo_id
    for _ in range(3):  # a GGUF's base can itself be a copy without weights; follow it a little way
        base = getattr(api.model_info(repo).card_data, "base_model", None)
        base = base[0] if isinstance(base, list) and base else base
        if not base:
            return {"error": "Its model card doesn't say which model it was made from, so the original weights "
                             "can't be found."}
        info = api.model_info(base, files_metadata=True)
        weights = sum(s.size or 0 for s in info.siblings or [] if s.rfilename.endswith(".safetensors"))
        if weights:
            break
        repo = base
    else:
        return {"error": "Couldn't find the original weights it was made from."}
    params = info.safetensors.total if info.safetensors else None
    arch = ((info.config or {}).get("architectures") or [None])[0]
    if info.gated:
        try:
            api.auth_check(base)
        except (GatedRepoError, HfHubHTTPError):
            mirror = _mirror(api, base, params)
            if not mirror:
                return {"error": f"The original, {base}, needs permission to download. Accept its licence on Hugging "
                                 "Face and add your token in Settings → Accounts."}
            base = mirror
    return {"repo": base, "params": params, "bytes": weights, "architecture": arch}


def _mirror(api, base: str, params: int | None) -> str | None:
    """An ungated copy of a gated original from a known source, with the same name and number of parameters."""
    name = base.split("/")[1].lower()
    for author in MIRRORS:
        for m in api.list_models(author=author, search=base.split("/")[1], limit=20):
            if m.id.split("/")[1].lower() != name:
                continue
            info = api.model_info(m.id)
            if not info.gated and info.safetensors and info.safetensors.total == params:
                return m.id
    return None


def chat_plan(original: dict) -> dict | None:
    """How to hold the original while training, from the graphics memory here: at bfloat16 on one card if it fits,
    otherwise in 4 bits, across several cards if one isn't enough. None if it can't fit at all."""
    b = _billions(original)
    cards = sorted((g for g in gpu.list_gpus() if g.get("uuid") != "apple-gpu"), key=lambda g: -g["memory_total"])
    if not cards or not b:
        return None
    biggest, total = cards[0]["memory_total"], sum(g["memory_total"] for g in cards)
    for mode, pool, use in (("bf16", biggest, cards[:1]), ("4bit", biggest, cards[:1]),
                            ("bf16", total, cards), ("4bit", total, cards)):
        need = CHAT_NEEDS[mode](b)
        if need <= pool * 0.9:
            return {"mode": mode, "cards": [g["index"] for g in use], "needs": need,
                    "card": " + ".join(g["name"].replace("NVIDIA ", "").replace("GeForce ", "") for g in use)}
    return None


def chat_models() -> list[dict]:
    """Installed GGUF chat models, with the original each trains on, how it would train here, and about how long an
    example takes. Trained models aren't offered (train the one they came from instead)."""
    out = []
    for m in db.list_models():
        meta = m.get("meta") or {}
        if m["task"] != "chat" or m["engine"] != "llamacpp" or meta.get("trained"):
            continue
        original = original_for(m)
        plan = chat_plan(original) if not original.get("error") else None
        seconds = None
        if plan:
            bw = gpu.memory_bandwidth(plan["cards"][0])
            seconds = (0.45 + 0.07 * _billions(original)) * (MEASURED_BANDWIDTH / bw if bw else 1.0)
            seconds *= 1.3 if len(plan["cards"]) > 1 else 1.0
        why = original.get("error") or (None if plan else
                                        f"Training it needs about {CHAT_NEEDS['4bit'](_billions(original)) / GB:.0f} "
                                        "GB of graphics memory, more than this computer has.")
        folder = ORIGINALS_DIR / str(original.get("repo", "")).replace("/", "--")
        out.append({"id": m["id"], "repo_id": m["repo_id"], "title": meta.get("title") or m["id"],
                    "original": original.get("repo"), "original_bytes": original.get("bytes"),
                    "downloaded": bool(original.get("repo")) and (folder / ".complete").exists(), "plan": plan,
                    "seconds_per_example": round(seconds, 2) if seconds else None, "why_not": why})
    return out


def chat_ready(mode: str | None = None) -> dict:
    """Whether this computer can train chat models: the AI libraries with PEFT (and bitsandbytes, to train in 4 bits),
    and an NVIDIA graphics card."""
    state = ready()
    if not state["ok"]:
        return state
    if mode == "4bit" and importlib.util.find_spec("bitsandbytes") is None:
        return {"ok": False, "missing": "peft", "reason": "Training this chat model needs one more library "
                "(bitsandbytes), added after your AI libraries were installed. Install it: a small download."}
    return state


def chat_defaults(preset: str, examples: int) -> dict:
    """Passes over the examples: more when there are few. Four examples a step."""
    passes = examples * (5 if examples < 50 else 3 if examples < 500 else 2)
    return {"steps": max(15, min(2000, math.ceil(passes / 4))), "accumulate": 4, "rank": 16, "learning_rate": 2e-4,
            "max_tokens": 1024 if preset == "chats" else 512}


def read_chats(files: list[tuple[str, bytes]], typed: list[dict]) -> list[list[dict]]:
    """Example conversations from .jsonl/.json (OpenAI's {"messages": [...]}, or prompt and reply fields), .csv (a
    question and an answer column) and pairs typed in the app. Each is a list of {"role", "content"}."""
    rows: list = list(typed or [])
    for name, data in files:
        text = data.decode("utf-8-sig", errors="replace")
        low = name.lower()
        try:
            if low.endswith(".jsonl"):
                rows += [json.loads(line) for line in text.splitlines() if line.strip()]
            elif low.endswith(".json"):
                loaded = json.loads(text)
                rows += loaded if isinstance(loaded, list) else [loaded]
            elif low.endswith(".csv"):
                import csv

                table = [r for r in csv.reader(text.splitlines()) if len(r) >= 2 and any(c.strip() for c in r[:2])]
                if table and table[0][0].strip().lower() in ("prompt", "question", "input", "instruction", "user",
                                                             "q"):
                    table = table[1:]
                rows += [{"prompt": r[0], "reply": r[1]} for r in table]
            else:
                raise TrainError(f"{name}: use a .jsonl, .json or .csv file for example chats.")
        except json.JSONDecodeError as e:
            raise TrainError(f"Couldn't read {name}: {e}") from None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("messages"), list):
            msgs = [{"role": m.get("role"), "content": str(m.get("content") or "")} for m in r["messages"]
                    if isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")]
        else:
            ask = next((r[k] for k in ("prompt", "question", "input", "instruction", "user") if r.get(k)), None)
            reply = next((r[k] for k in ("reply", "response", "answer", "output", "completion", "assistant")
                          if r.get(k)), None)
            msgs = [{"role": "user", "content": str(ask)}, {"role": "assistant", "content": str(reply)}] \
                if ask and reply else []
        if any(m["role"] == "assistant" and m["content"].strip() for m in msgs):
            out.append(msgs)
    return out[:MAX_CHATS]


def read_writing(files: list[tuple[str, bytes]], pasted: str) -> list[str]:
    """Writing to learn a voice from: text, Markdown and PDF files, and text pasted into the app."""
    from .knowledge.extract import ExtractError, extract

    texts = [pasted] if (pasted or "").strip() else []
    for name, data in files:
        try:
            parts, _, _ = extract(data, name, 5_000_000)
        except ExtractError as e:
            raise TrainError(f"{name}: {e}") from None
        texts.append("\n\n".join(t for _, t in parts))
    return [t.strip() for t in texts if t.strip()]


def _sample_asks(chats: list[list[dict]], seed: str) -> list[str]:
    """Two questions from the examples (to see it answer as taught) and one of its own (to see it carry over)."""
    asks = []
    for c in chats:
        first = next(i for i, m in enumerate(c) if m["role"] == "assistant")
        if first > 0 and c[first - 1]["role"] == "user":
            asks.append(c[first - 1]["content"])
    return random.Random(seed).sample(asks, min(2, len(asks))) + ["Introduce yourself in a few sentences."]


def create_chat(model_id: str, preset: str, name: str, files: list[tuple[str, bytes]], pasted: str = "",
                typed: list[dict] | None = None, steps: int | None = None) -> dict:
    """Check everything, save the examples, and start training a chat model."""
    model = db.get_model(model_id)
    if not model or model["task"] != "chat" or model["engine"] != "llamacpp" or (model.get("meta") or {}).get("trained"):
        raise TrainError("Choose an installed chat model to train.")
    if preset not in CHAT_PRESETS:
        raise TrainError("Choose what to teach it: your writing voice or example chats.")
    original = original_for(model)
    if original.get("error"):
        raise TrainError(original["error"])
    plan = chat_plan(original)
    if not plan:
        raise TrainError(f"Training it needs about {CHAT_NEEDS['4bit'](_billions(original)) / GB:.0f} GB of graphics "
                         "memory, more than this computer has. Choose a smaller chat model.")
    state = chat_ready(plan["mode"])
    if not state["ok"]:
        raise TrainError(state["reason"])
    if preset == "voice":
        writing = read_writing(files, pasted)
        words = sum(len(t.split()) for t in writing)
        if words < MIN_WORDS:
            raise TrainError(f"Add more of your writing: at least {MIN_WORDS} words (there are {words}). 2,000 or "
                             "more works best.")
        count = max(1, words // 180)  # pieces of about 256 tokens
    else:
        chats = read_chats(files, typed or [])
        if len(chats) < MIN_CHATS:
            raise TrainError(f"Add at least {MIN_CHATS} example chats (there are {len(chats)}). 50 or more works "
                             "best.")
        count = len(chats)
    if any(r["status"].get("stage") in ACTIVE for r in list_runs()):
        raise TrainError("Another training run is going. Wait for it to finish, or stop it first.")

    from .engines import llamacpp

    rid = uuid.uuid4().hex[:12]
    folder = TRAIN_DIR / rid
    if preset == "voice":
        (folder / "data" / "voice").mkdir(parents=True)
        for n, text in enumerate(writing, 1):
            (folder / "data" / "voice" / f"{n:03d}.txt").write_text(text, encoding="utf-8")
    else:
        (folder / "data").mkdir(parents=True)
        (folder / "data" / "chats.jsonl").write_text(
            "\n".join(json.dumps({"messages": c}, ensure_ascii=False) for c in chats), encoding="utf-8")
    d = chat_defaults(preset, count)
    run = {
        "type": "chat", "name": (name or "").strip()[:80] or ("My voice" if preset == "voice" else "My assistant"),
        "preset": preset, "trigger": "", "what": "", "model": model["id"],
        "model_title": (model.get("meta") or {}).get("title") or model["id"], "repo_id": model["repo_id"],
        "model_path": model["path"], "kind": "chat", "examples": count,
        "original_repo": original["repo"], "original_bytes": original.get("bytes"),
        "original_path": str(ORIGINALS_DIR / original["repo"].replace("/", "--")),
        "mode": plan["mode"], "cards": plan["cards"], "rank": d["rank"], "learning_rate": d["learning_rate"],
        "accumulate": d["accumulate"], "max_tokens": d["max_tokens"],
        "steps": max(10, min(4000, int(steps))) if steps else d["steps"],
        "quant": _quant(model),
        "matched_path": str(MATCHED_DIR / f"{original['repo'].replace('/', '--')}-{_quant(model)}.gguf"),
        "converter": str(CONVERTER_DIR / llamacpp.DEFAULT_TAG),
        "llama_tag": llamacpp.DEFAULT_TAG,
        "llama_server": str(llamacpp.installer.binary()), "created": time.time(),
    }
    if preset == "chats":
        run["sample_prompts"] = _sample_asks(chats, rid)
    (folder / "run.json").write_text(json.dumps(run, indent=2))
    _status(rid, stage="queued", message="Starting")
    try:
        _start(rid, run)
    except TrainError as e:
        _status(rid, stage="error", message=str(e))
    return get(rid)


def _register(rid: str, gguf: str | None) -> None:
    """Add a finished chat run to the installed models: the GGUF made from the original it trained on (see
    workers/train_chat.matching_gguf), with the trained adapter."""
    folder = _folder(rid)
    run = _read(folder / "run.json")
    base = db.get_model(run["model"])
    if not base or not gguf:
        return
    meta = {k: v for k, v in (base.get("meta") or {}).items() if k != "title"}
    model_id = run.get("registered") or _unique_id(f"{_slug(run['name'])}-{base['id']}")
    db.add_model(id=model_id, repo_id=base["repo_id"], task="chat", engine="llamacpp", path=gguf,
                 files=[Path(gguf).name], size_bytes=Path(gguf).stat().st_size,
                 meta={**meta, "title": f"{run['name']} ({run.get('model_title') or base['id']})",
                       "lora": (folder / "lora.gguf").relative_to(HOME).as_posix(), "trained": rid,
                       "base": base["id"]})
    run["registered"] = model_id
    (folder / "run.json").write_text(json.dumps(run, indent=2))


def _unregister(rid: str) -> None:
    from .workers.manager import manager

    run = _read(_folder(rid) / "run.json")
    if run.get("registered") and db.get_model(run["registered"]):
        manager.unload(run["registered"])
        db.delete_model(run["registered"])


# Compressions llama-quantize makes without extra calibration data. Others (Unsloth's dynamic UD-..._XL, IQ2...) are
# made as their nearest plain kind.
QUANTS = ("Q4_0", "Q4_1", "Q5_0", "Q5_1", "Q8_0", "Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L", "Q4_K_S", "Q4_K_M", "Q5_K_S",
          "Q5_K_M", "Q6_K", "IQ4_NL", "IQ4_XS", "MXFP4_MOE", "BF16", "F16", "F32")


def _quant(model: dict) -> str:
    """How the installed GGUF is compressed, as llama-quantize names it, so the trained model's copy matches."""
    q = str((model.get("meta") or {}).get("quant") or "").upper().removeprefix("UD-")
    if not q:
        found = re.search(r"(?i)(?:^|[-_.])((?:UD-)?I?Q\d[A-Z0-9_]*|BF16|F16|F32|MXFP4(?:_MOE)?)\.gguf$",
                          Path(model["path"]).name)
        q = found.group(1).upper().removeprefix("UD-") if found else ""
    q = re.sub(r"_XL$", "_M", q)
    if q == "MXFP4":
        q = "MXFP4_MOE"
    return q if q in QUANTS else "Q4_K_M"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "trained"


def _unique_id(base: str) -> str:
    out, n = base[:80], 2
    while db.get_model(out):
        out, n = f"{base[:76]}-{n}", n + 1
    return out
