"""Sensible default generation settings per model family, so beginners never touch a slider."""

from __future__ import annotations

# Ordered: first match on the lowercased repo id wins.
IMAGE_PRESETS = [
    ("turbo", {"steps": 2, "guidance": 0.0, "width": 512, "height": 512}),
    ("lightning", {"steps": 4, "guidance": 0.0, "width": 1024, "height": 1024}),
    ("flux.1-schnell", {"steps": 4, "guidance": 0.0, "width": 1024, "height": 1024}),
    ("flux", {"steps": 28, "guidance": 3.5, "width": 1024, "height": 1024}),
    ("stable-diffusion-3", {"steps": 28, "guidance": 7.0, "width": 1024, "height": 1024}),
    ("xl", {"steps": 30, "guidance": 7.0, "width": 1024, "height": 1024}),
    ("ssd-1b", {"steps": 30, "guidance": 7.0, "width": 1024, "height": 1024}),
    ("", {"steps": 25, "guidance": 7.5, "width": 512, "height": 512}),
]

VIDEO_PRESETS = [
    ("wan", {"steps": 30, "guidance": 5.0, "width": 832, "height": 480, "num_frames": 33, "fps": 16}),
    ("ltx", {"steps": 40, "guidance": 3.0, "width": 704, "height": 480, "num_frames": 65, "fps": 24}),
    ("cogvideo", {"steps": 50, "guidance": 6.0, "width": 720, "height": 480, "num_frames": 49, "fps": 8}),
    ("", {"steps": 30, "guidance": 5.0, "width": 512, "height": 512, "num_frames": 25, "fps": 8}),
]

# Quality buttons in the UI scale the preset's step count.
QUALITY = {"fast": 0.5, "balanced": 1.0, "best": 1.6}


def _match(table, repo_id: str) -> dict:
    rid = repo_id.lower()
    for key, preset in table:
        if key in rid:
            return dict(preset)
    return dict(table[-1][1])


def for_model(model: dict) -> dict:
    if model["task"] == "image":
        return _match(IMAGE_PRESETS, model["repo_id"])
    if model["task"] == "video":
        return _match(VIDEO_PRESETS, model["repo_id"])
    return {}


def apply(model: dict, params: dict) -> dict:
    """Fill unset params from the preset and apply the quality multiplier."""
    preset = for_model(model)
    if model["task"] == "image":
        from .samplers import options_for

        opts = options_for(model["repo_id"], model["path"])
        if not params.get("sampler") and opts["default"]:
            params["sampler"] = opts["default"]
        elif params.get("sampler") and params["sampler"] != "builtin" and not opts["samplers"]:
            params.pop("sampler")  # model can't switch samplers; keep its own
    quality = params.pop("quality", None)
    out = {**preset, **{k: v for k, v in params.items() if v is not None}}
    if quality in QUALITY and params.get("steps") is None and preset.get("steps"):
        out["steps"] = max(1, round(preset["steps"] * QUALITY[quality]))
    # Keep dimensions friendly for VAEs (multiples of 8; video models prefer 32).
    mult = 32 if model["task"] == "video" else 8
    for k in ("width", "height"):
        if out.get(k):
            out[k] = max(mult, int(out[k]) // mult * mult)
    if model["task"] == "video" and out.get("num_frames"):
        # Most video VAEs want 4k+1 frames (Wan, CogVideoX) or 8k+1 (LTX); 8k+1 satisfies both.
        n = int(out["num_frames"])
        out["num_frames"] = max(9, (n - 1) // 8 * 8 + 1)
    return out
