"""Paths and settings. Everything lives under WANNA_HOME (default ~/.wanna)."""

from __future__ import annotations

import json
import os
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

DEFAULT_SETTINGS = {
    # Hugging Face token, needed for gated models (e.g. FLUX.1).
    "hf_token": "",
    # Optional Brave Search API key; Code's web search uses it before the local SearXNG.
    "brave_api_key": "",
    # When true, /v1 and /api require a valid API key (except from the bundled UI on localhost).
    "require_api_key": False,
    # Unload a model automatically after this many idle minutes. 0 disables.
    "idle_unload_minutes": 0,
    # Default context length for chat models.
    "default_context": 8192,
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
