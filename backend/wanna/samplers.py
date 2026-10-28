"""Samplers (diffusers "schedulers") people can pick for picture models.

Kept free of heavy imports so the web server can decide what to offer without loading PyTorch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# id -> (diffusers class, extra config, label shown to people). Order is the order in the menu.
SAMPLERS: dict[str, tuple[str, dict, str]] = {
    "dpmpp_2m_karras": ("DPMSolverMultistepScheduler", {"use_karras_sigmas": True, "algorithm_type": "dpmsolver++"},
                        "Fast and detailed (DPM++ 2M Karras)"),
    "euler_a": ("EulerAncestralDiscreteScheduler", {}, "Creative, more variety (Euler a)"),
    "euler": ("EulerDiscreteScheduler", {}, "Smooth and steady (Euler)"),
    "unipc": ("UniPCMultistepScheduler", {}, "Good in few steps (UniPC)"),
    "ddim": ("DDIMScheduler", {}, "Classic (DDIM)"),
}
DEFAULT_SAMPLER = "dpmpp_2m_karras"

# Built-in schedulers that belong to the same family as everything in SAMPLERS, so swapping is safe.
# Flow-matching models (FLUX, SD3, Wan...) use a single scheduler and are deliberately absent.
SWAPPABLE = {
    "PNDMScheduler", "DDIMScheduler", "DDPMScheduler", "LMSDiscreteScheduler", "EulerDiscreteScheduler",
    "EulerAncestralDiscreteScheduler", "DPMSolverMultistepScheduler", "DPMSolverSinglestepScheduler",
    "UniPCMultistepScheduler", "HeunDiscreteScheduler", "KDPM2DiscreteScheduler",
    "KDPM2AncestralDiscreteScheduler", "DEISMultistepScheduler",
}

# Distilled models are trained for one specific sampler and step count; changing it ruins the output.
DISTILLED = re.compile(r"(turbo|lightning|lcm|hyper|schnell|distill)", re.IGNORECASE)


def builtin_scheduler(model_dir: str | Path) -> str | None:
    try:
        cfg = json.loads((Path(model_dir) / "scheduler" / "scheduler_config.json").read_text())
        return cfg.get("_class_name")
    except (OSError, json.JSONDecodeError):
        return None


def options_for(repo_id: str, model_dir: str | Path) -> dict:
    """What the picture page should offer for this model: {"samplers": [...], "default": id | None}."""
    builtin = builtin_scheduler(model_dir)
    if builtin not in SWAPPABLE or DISTILLED.search(repo_id):
        return {"samplers": [], "default": None, "builtin": builtin}
    choices = [{"id": k, "label": v[2]} for k, v in SAMPLERS.items()]
    choices.append({"id": "builtin", "label": f"This model's original ({builtin.removesuffix('Scheduler')})"})
    return {"samplers": choices, "default": DEFAULT_SAMPLER, "builtin": builtin}
