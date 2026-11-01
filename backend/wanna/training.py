"""Training LoRAs for picture models: your own subject (a person, a pet, a product) or style, from a few pictures.

Each training run is a folder in ~/.wanna/training/<id>: run.json (what to train), status.json (how it went),
pictures/ (the examples), lora/ (the result) and samples/ (pictures made with it). The work happens in its own process
(workers/train.py) on one graphics card; this module starts it, follows its progress and keeps the list.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import db, gpu
from .config import HOME

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
        return json.loads(path.read_text())
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
    if status.get("stage") in ("queued", "preparing", "training", "saving", "samples") and rid not in _procs:
        status = {**status, "stage": "interrupted", "message": "Stopped when wanna.sh closed. Start it again."}
    samples = sorted((folder / "samples").glob("*.png")) if (folder / "samples").exists() else []
    return {
        "id": rid, "name": run["name"], "preset": run["preset"], "trigger": run["trigger"], "what": run.get("what", ""),
        "model": run["model"], "model_title": run.get("model_title"), "kind": run["kind"], "steps": run["steps"],
        "pictures": len(list((folder / "pictures").iterdir())) if (folder / "pictures").exists() else 0,
        "created": run["created"], "status": status,
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
    if any(r["status"].get("stage") in ("queued", "preparing", "training", "saving", "samples") for r in list_runs()):
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
    card = _pick_card(run["kind"])
    folder = _folder(rid)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(card), "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
           "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "WANNA_SERVER_PID": str(os.getpid()),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    (folder / "stop").unlink(missing_ok=True)
    log_file = open(folder / "train.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "wanna.workers.train", str(folder)], stdout=subprocess.PIPE,
                            stderr=log_file, text=True, env=env, **kwargs)
    _procs[rid] = proc
    _status(rid, stage="preparing", message="Starting", gpu=card, started=time.time(), pid=proc.pid)
    threading.Thread(target=_follow, args=(rid, proc, log_file), daemon=True, name=f"train-{rid}").start()
    log.info("Training %s (%s) on GPU %d", rid, run["name"], card)


def _follow(rid: str, proc: subprocess.Popen, log_file) -> None:
    """Keep status.json up to date from the trainer's progress lines."""
    last = None
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        last = msg
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
    shutil.rmtree(folder, ignore_errors=True)


def rename(rid: str, name: str) -> dict:
    p = _folder(rid) / "run.json"
    run = _read(p)
    run["name"] = name.strip()[:80] or run["name"]
    p.write_text(json.dumps(run, indent=2))
    return get(rid)


# --- using a trained style -------------------------------------------------------------------------------------------

def for_model(model: dict) -> list[dict]:
    """Finished styles that work with this picture model: ones trained on the same model (by its Hugging Face repo)."""
    return [{"id": r["id"], "name": r["name"], "trigger": r["trigger"], "prompt": r["prompt"]}
            for r in list_runs() if r["ready"] and _read(_folder(r["id"]) / "run.json").get("repo_id") == model["repo_id"]]


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
