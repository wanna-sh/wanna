"""Paths and settings. Everything lives under WANNA_HOME (default ~/.wanna)."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

HOME = Path(os.environ.get("WANNA_HOME", Path.home() / ".wanna")).expanduser()
MODELS_DIR = HOME / "models"
OUTPUTS_DIR = HOME / "outputs"
UPLOADS_DIR = HOME / "uploads"
ENGINES_DIR = HOME / "engines"
LOGS_DIR = HOME / "logs"
DB_PATH = HOME / "wanna.db"
SETTINGS_PATH = HOME / "settings.json"

for _d in (MODELS_DIR, OUTPUTS_DIR, UPLOADS_DIR, ENGINES_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Running wanna.sh itself in Docker with Code turned on (docker-compose.code.yml). Containers wanna.sh starts
# (the Code sandbox, SearXNG) are created by the host's Docker, so:
# - WANNA_HOST_HOME is where the data folder is on the host, for their bind mounts;
# - WANNA_DOCKER_NETWORK is a network shared with them, so wanna.sh reaches them by name, not 127.0.0.1.
HOST_HOME = os.environ.get("WANNA_HOST_HOME") or None
DOCKER_NETWORK = os.environ.get("WANNA_DOCKER_NETWORK") or None


def host_path(path: Path) -> str:
    """Where `path` (inside the data folder) is on the Docker host. The same path unless wanna.sh runs in Docker."""
    if not HOST_HOME:
        return str(path)
    return str(Path(HOST_HOME) / Path(path).resolve().relative_to(HOME.resolve()))

DEFAULT_SETTINGS = {
    # Hugging Face token, needed for gated models (e.g. FLUX.1).
    "hf_token": "",
    # Optional Brave Search API key; Code's web search uses it before the local SearXNG.
    "brave_api_key": "",
    # When true, /v1 and /api require a valid API key (except from the bundled UI on localhost).
    "require_api_key": False,
    # Extra host names wanna.sh answers to (for example "mypc.local"), on top of WANNA_ALLOWED_HOSTS.
    "allowed_hosts": [],
    # Unload a model automatically after this many idle minutes. 0 disables.
    "idle_unload_minutes": 0,
    # Default context length for chat models.
    "default_context": 8192,
    # Let chat models bigger than graphics and system memory together run by reading from the drive (very slow).
    "stream_from_drive": False,
    # Where new model downloads are saved (a full path). Blank: the models folder in the data folder.
    "models_dir": "",
}

_lock = threading.Lock()


def load_settings() -> dict:
    with _lock:
        data = dict(DEFAULT_SETTINGS)
        if SETTINGS_PATH.exists():
            try:
                data.update(json.loads(SETTINGS_PATH.read_text()))
            except json.JSONDecodeError:
                pass
        if os.environ.get("HF_TOKEN") and not data["hf_token"]:
            data["hf_token"] = os.environ["HF_TOKEN"]
        return data


def save_settings(patch: dict) -> dict:
    current = load_settings()
    current.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
    with _lock:
        SETTINGS_PATH.write_text(json.dumps(current, indent=2))
    return current


def hf_token() -> str | None:
    return load_settings()["hf_token"] or None


# Left in every other folder models are saved to, so deleting a model only ever removes a folder wanna.sh made.
MODELS_MARKER = ".wanna-models"


def models_dir() -> Path:
    """Where new downloads are saved: the folder chosen in Settings → Models & memory, or models/ in the data folder.

    Models already downloaded stay where they are: the database has their paths.
    """
    chosen = str(load_settings().get("models_dir") or "").strip()
    return Path(chosen).expanduser() if chosen else MODELS_DIR


def is_models_root(folder: Path) -> bool:
    """Whether wanna.sh saves (or once saved) models in this folder."""
    try:
        return folder.resolve() == MODELS_DIR.resolve() or (folder / MODELS_MARKER).is_file()
    except OSError:
        return False


def disk_free(path: Path) -> int:
    """Free space on the drive `path` is on (it needn't exist yet), or 0 if the drive isn't there (unplugged)."""
    for p in (path, *path.parents):
        try:
            return shutil.disk_usage(p).free
        except OSError:
            continue
    return 0
