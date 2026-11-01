"""Train a LoRA for a picture model (Stable Diffusion 1.x/2.x or SDXL), in its own process.

    python -m wanna.workers.train <run folder>

The run folder holds run.json (what to train) and pictures/ (the examples). Progress goes to stdout as one JSON
object per line; the LoRA is saved as lora/pytorch_lora_weights.safetensors, in the format diffusers'
load_lora_weights reads, and sample pictures as samples/*.png.

To fit consumer graphics cards, the pictures and the caption are turned into the model's own representation once, up
front; then only the UNet stays on the card, frozen at half precision, with gradient checkpointing, while the small
LoRA trains at full precision.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def say(**msg) -> None:
    print(json.dumps(msg), flush=True)


def kind_of(model_path: str) -> str | None:
    """"sd" or "sdxl" for pipelines this can train, from the model's model_index.json; None otherwise."""
    try:
        cls = json.loads((Path(model_path) / "model_index.json").read_text()).get("_class_name", "")
    except (OSError, json.JSONDecodeError):
        return None
    if cls == "StableDiffusionXLPipeline":
        return "sdxl"
    if cls == "StableDiffusionPipeline":
        return "sd"
    return None


def caption(run: dict) -> str:
    """What every example is captioned with: the trigger word, plus what it is (subject) or "style"."""
    word, what = run["trigger"], (run.get("what") or "").strip()
    if run["preset"] == "style":
        return f"a picture in the style of {word}"
    return f"a photo of {word} {what}".strip()


def main(folder: Path) -> None:
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    run = json.loads((folder / "run.json").read_text())
    started = time.time()
    say(stage="preparing", message="Loading the picture model")

    import diffusers
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict

    sdxl = run["kind"] == "sdxl"
    device = "cuda"
    bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    kw = {"torch_dtype": dtype, **({"variant": run["variant"]} if run.get("variant") else {})}
    Pipeline = diffusers.StableDiffusionXLPipeline if sdxl else diffusers.StableDiffusionPipeline
    pipe = Pipeline.from_pretrained(run["model_path"], **kw)
    pipe.set_progress_bar_config(disable=True)  # progress goes to wanna.sh as JSON instead
    if sdxl and dtype == torch.float16:
        # SDXL's own VAE overflows at float16 (black pictures); without bfloat16, encode at full precision.
        pipe.vae.to(torch.float32)
    size = int(run["resolution"])

    # 1. The pictures, as latents (each also mirrored, for variety), and the caption, as text embeddings.
    pictures = sorted(p for p in (folder / "pictures").iterdir() if p.suffix.lower() in PICTURE_SUFFIXES)
    pipe.vae.to(device)
    latents = []
    for n, path in enumerate(pictures, 1):
        say(stage="preparing", message=f"Reading picture {n} of {len(pictures)}")
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        im = ImageOps.fit(im, (size, size), Image.Resampling.LANCZOS)  # centre crop to a square
        for flip in (False, True):
            pic = ImageOps.mirror(im) if flip else im
            x = torch.from_numpy(np.array(pic)).float().permute(2, 0, 1) / 127.5 - 1
            x = x.unsqueeze(0).to(device, pipe.vae.dtype)
            with torch.no_grad():
                lat = pipe.vae.encode(x).latent_dist.sample() * pipe.vae.config.scaling_factor
            latents.append(lat.to("cpu", torch.float32))
    pipe.vae.to("cpu")
    for enc in ("text_encoder", "text_encoder_2"):
        if getattr(pipe, enc, None) is not None:
            getattr(pipe, enc).to(device)
    with torch.no_grad():
        if sdxl:
            embeds, _, pooled, _ = pipe.encode_prompt(caption(run), device=device, num_images_per_prompt=1,
                                                      do_classifier_free_guidance=False)
        else:
            embeds, _ = pipe.encode_prompt(caption(run), device=device, num_images_per_prompt=1,
                                           do_classifier_free_guidance=False)
            pooled = None
    for enc in ("text_encoder", "text_encoder_2"):
        if getattr(pipe, enc, None) is not None:
            getattr(pipe, enc).to("cpu")
    torch.cuda.empty_cache()

    # 2. The UNet: frozen at half precision, with a LoRA on its attention layers that trains at full precision.
    unet = pipe.unet
    unet.requires_grad_(False)
    unet.to(device, dtype)
    rank = int(run["rank"])
    unet.add_adapter(LoraConfig(r=rank, lora_alpha=rank, init_lora_weights="gaussian",
                                target_modules=["to_k", "to_q", "to_v", "to_out.0"]))
    params = [p for p in unet.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()
    unet.enable_gradient_checkpointing()
    unet.train()
    optimizer = torch.optim.AdamW(params, lr=float(run["learning_rate"]), weight_decay=1e-2)
    noise_scheduler = diffusers.DDPMScheduler.from_config(pipe.scheduler.config)
    prediction = noise_scheduler.config.prediction_type
    embeds = embeds.to(device, dtype)
    extra = {}
    if sdxl:
        # SDXL is told the picture's size and crop: square, uncropped, at the training size.
        time_ids = torch.tensor([[size, size, 0, 0, size, size]], device=device, dtype=dtype)
        extra = {"added_cond_kwargs": {"text_embeds": pooled.to(device, dtype), "time_ids": time_ids}}

    # 3. Train.
    steps = int(run["steps"])
    stop_file = folder / "stop"
    import os

    import psutil

    try:  # wanna.sh: if it's gone, nobody is following this run
        parent = psutil.Process(int(os.environ["WANNA_SERVER_PID"]))
    except (KeyError, ValueError, psutil.Error):
        parent = None
    losses: list[float] = []
    t0 = time.time()
    for step in range(1, steps + 1):
        if stop_file.exists():
            say(stage="stopped", message="Stopped")
            return
        if parent and step % 20 == 0 and not parent.is_running():
            return
        lat = random.choice(latents).to(device, dtype)
        noise = torch.randn_like(lat)
        t = torch.randint(0, noise_scheduler.config.num_train_timesteps, (1,), device=device).long()
        noisy = noise_scheduler.add_noise(lat, noise, t)
        target = noise if prediction == "epsilon" else noise_scheduler.get_velocity(lat, noise, t)
        with torch.autocast("cuda", dtype=dtype):
            pred = unet(noisy, t, embeds, **extra).sample
        loss = torch.nn.functional.mse_loss(pred.float(), target.float())
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(loss.item())
        if step % 10 == 0 or step == steps:
            per_step = (time.time() - t0) / step
            say(stage="training", step=step, steps=steps, loss=round(sum(losses[-50:]) / len(losses[-50:]), 4),
                seconds_left=round(per_step * (steps - step)))
        if not math.isfinite(losses[-1]):
            raise RuntimeError("Training became unstable (the loss stopped being a number). Try a lower learning "
                               "rate or fewer steps.")

    # 4. Save the LoRA, in the format diffusers' load_lora_weights reads.
    say(stage="saving", message="Saving the trained style")
    unet.eval()
    lora = convert_state_dict_to_diffusers(get_peft_model_state_dict(unet))
    out = folder / "lora"
    Pipeline.save_lora_weights(out, unet_lora_layers=lora)
    del optimizer
    torch.cuda.empty_cache()

    # 5. Sample pictures with the trained LoRA, so the result can be judged at once.
    say(stage="samples", message="Making sample pictures")
    for p in params:
        p.data = p.data.to(dtype)
    pipe.to(device)
    if sdxl and dtype == torch.float16:
        pipe.vae.to(torch.float32)
    samples = folder / "samples"
    samples.mkdir(exist_ok=True)
    prompts = run.get("sample_prompts") or [caption(run)]
    seed = 1234
    for n, prompt in enumerate(prompts[:4]):
        gen = torch.Generator(device="cpu").manual_seed(seed + n)
        with torch.no_grad():
            image = pipe(prompt, num_inference_steps=30, guidance_scale=7.0, width=size, height=size,
                         generator=gen).images[0]
        image.save(samples / f"{n + 1}.png")
    say(stage="done", message="Done", seconds=round(time.time() - started),
        peak_gb=round(torch.cuda.max_memory_allocated() / 1e9, 1))


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except Exception as e:  # report every failure to wanna.sh as a message it can show
        import traceback

        traceback.print_exc(file=sys.stderr)
        text = str(e)
        if "out of memory" in text.lower():
            text = ("The graphics card ran out of memory. Stop other models, choose a smaller picture size, or train "
                    "a Stable Diffusion 1.5 model instead of SDXL.")
        say(stage="error", message=text[:600])
        sys.exit(1)
