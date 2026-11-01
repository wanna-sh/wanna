"""Train a LoRA for a chat model, in its own process, and turn it into a llama.cpp adapter.

    python -m wanna.workers.train_chat <run folder>

The run folder holds run.json (what to train) and data/: voice/*.txt (writing to learn to write like) or chats.jsonl
(example conversations, one {"messages": [...]} per line). Progress goes to stdout as one JSON object per line, as with
the picture trainer.

Chat models run in llama.cpp from GGUF files, which can't be trained, so this trains on the model's original weights
(downloaded once into models/originals/) and converts the LoRA with llama.cpp's own convert_lora_to_gguf.py: the
result, lora.gguf, runs on top of the GGUF model already installed. How the original is held depends on the memory
there is: at bfloat16 on one card when it fits, otherwise in 4 bits (QLoRA, with bitsandbytes), across several cards if
one isn't enough. Samples (replies with and without the LoRA) go to samples/replies.json.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from .train import say

# The layers LoRA trains: attention and the feed-forward block, in the names nearly every chat model uses.
TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
NOT_TEXT = ("vision", "visual", "audio", "image", "mm_projector", "multi_modal")  # towers of models that see or hear
NO_THINKING = {"enable_thinking": False}  # for chat templates that take it (Qwen3 and others); ignored elsewhere
VOICE_ASKS = ["Write something.", "Write a short post.", "What's on your mind?", "Tell me about your day.",
              "Write a few paragraphs in your own words.", "Share a thought.", "Write whatever you like.",
              "Write me something to read."]
VOICE_PROMPTS = ["Write a short message to a friend about your weekend.",
                 "Describe your favourite place in a few sentences.",
                 "Write a short opening paragraph for a blog post about learning something new."]


def download(run: dict) -> None:
    """Fetch the original weights, reporting progress by the folder's size against the expected total."""
    from huggingface_hub import snapshot_download

    dest = Path(run["original_path"])
    if (dest / ".complete").exists():
        return
    total = run.get("original_bytes") or 0
    done = threading.Event()
    error: list[BaseException] = []

    def fetch():
        try:
            snapshot_download(run["original_repo"], local_dir=dest, token=os.environ.get("HF_TOKEN") or None,
                              allow_patterns=["*.json", "*.safetensors", "tokenizer*", "*.model", "*.jinja", "*.txt"])
        except BaseException as e:  # reported below, in this process's main thread
            error.append(e)
        done.set()

    threading.Thread(target=fetch, daemon=True).start()
    while not done.wait(2):
        have = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) if dest.exists() else 0
        say(stage="downloading", message="Downloading the model's original weights (once)",
            done_bytes=have, total_bytes=total)
    if error:
        raise RuntimeError(f"Couldn't download {run['original_repo']}: {error[0]}")
    (dest / ".complete").touch()


def examples(run: dict, folder: Path, tok) -> list[tuple[list[int], list[int]]]:
    """(token ids, labels) per example. Writing is cut into blocks and learned whole; in example chats only the
    replies are learned (the rest is labelled -100, which the loss skips)."""
    max_len = int(run["max_tokens"])
    out = []
    if run["preset"] == "voice":
        conversations = [[{"role": "user", "content": random.Random(n).choice(VOICE_ASKS)},
                          {"role": "assistant", "content": piece}]
                         for n, piece in enumerate(_pieces(folder / "data" / "voice", tok, max_len // 2))]
    else:
        conversations = [json.loads(line)["messages"]
                         for line in (folder / "data" / "chats.jsonl").read_text(encoding="utf-8").splitlines()]
    for messages in conversations:
        ids = _ids(tok.apply_chat_template(messages, tokenize=True, **NO_THINKING))
        labels = [-100] * len(ids)
        for n, m in enumerate(messages):
            if m["role"] != "assistant":
                continue
            # Everything up to this reply is context; the reply (and its end-of-turn marker) is what's learned.
            # Models that reason first open a reply with an empty reasoning block when told not to reason: that's
            # context too, or the model learns to write one where chats have already put it.
            before = _ids(tok.apply_chat_template(messages[:n], add_generation_prompt=True, tokenize=True,
                                                  **NO_THINKING))
            through = _ids(tok.apply_chat_template(messages[:n + 1], tokenize=True, **NO_THINKING))
            if ids[:len(through)] == through:
                labels[len(before):len(through)] = through[len(before):]
            else:  # templates that rewrite earlier turns (dropping old reasoning, say): learn this turn on its own
                out.append((through[:max_len], ([-100] * len(before) + through[len(before):])[:max_len]))
        if any(x != -100 for x in labels[:max_len]):
            out.append((ids[:max_len], labels[:max_len]))
    return out


def _pieces(folder: Path, tok, size: int) -> list[str]:
    """The writing, cut at paragraph breaks into pieces of up to about `size` tokens. Each piece is learned as a
    reply to a general request (VOICE_ASKS), so the voice carries over to how the model answers in a chat, which
    learning the writing as plain text barely does."""
    pieces, current, length = [], [], 0
    for f in sorted(folder.glob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        for para in (p.strip() for p in text.split("\n\n")):
            if not para:
                continue
            n = len(tok(para, add_special_tokens=False)["input_ids"])
            if current and length + n > size:
                pieces.append("\n\n".join(current))
                current, length = [], 0
            current.append(para)
            length += n
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _ids(x) -> list[int]:
    """apply_chat_template's token ids, whichever shape this version of transformers returns them in."""
    if isinstance(x, dict) or hasattr(x, "keys"):
        x = x["input_ids"]
    return list(x[0]) if x and isinstance(x[0], list) else list(x)


def load(run: dict, dtype):
    """The original model, frozen, held as run["mode"] says: "bf16" or "4bit", on the cards this process can see."""
    import torch
    import transformers

    kw: dict = {"dtype": dtype, "low_cpu_mem_usage": True}
    cards = torch.cuda.device_count()
    if cards > 1:
        # Several cards: layers spread over them in order, each left room for its share of the training.
        kw["device_map"] = "auto"
        kw["max_memory"] = {i: int(torch.cuda.mem_get_info(i)[0] * 0.8) for i in range(cards)}
    else:
        kw["device_map"] = {"": 0}
    if run["mode"] == "4bit":
        kw["quantization_config"] = transformers.BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype)
    path = run["original_path"]
    try:
        model = transformers.AutoModelForCausalLM.from_pretrained(path, **kw)
    except ValueError:  # models that also see pictures load as image-text-to-text; only their text part is trained
        model = transformers.AutoModelForImageTextToText.from_pretrained(path, **kw)
    model.config.use_cache = False
    return model


def main(folder: Path) -> None:
    import torch

    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    started = time.time()
    download(run)

    say(stage="preparing", message="Reading your examples")
    import transformers
    from peft import LoraConfig, get_peft_model

    tok = transformers.AutoTokenizer.from_pretrained(run["original_path"])
    data = examples(run, folder, tok)
    if not data:
        raise RuntimeError("There's nothing to learn from in those examples. Add more writing, or example chats with "
                           "replies.")

    say(stage="preparing", message="Loading the model" + (" in 4 bits" if run["mode"] == "4bit" else ""))
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = load(run, dtype)
    # Not peft's prepare_model_for_kbit_training: it turns every weight left unquantized to full precision, the
    # embeddings included, which costs more memory than the rest of an 8B model in 4 bits.
    model.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    targets = sorted({name for name, mod in model.named_modules()
                      if name.split(".")[-1] in TARGETS and not any(w in name for w in NOT_TEXT)
                      and hasattr(mod, "weight")})
    rank = int(run["rank"])
    model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05, target_modules=targets,
                                             task_type="CAUSAL_LM"))
    params = [p for p in model.parameters() if p.requires_grad]
    for p in params:
        p.data = p.data.float()  # the LoRA itself trains at full precision
    optimizer = torch.optim.AdamW(params, lr=float(run["learning_rate"]), weight_decay=0.0)
    steps, accumulate = int(run["steps"]), int(run["accumulate"])
    warmup = max(1, steps // 20)
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda s: min(1.0, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / steps))))
    device = model.get_input_embeddings().weight.device

    import psutil

    try:  # wanna.sh: if it's gone, nobody is following this run
        parent = psutil.Process(int(os.environ["WANNA_SERVER_PID"]))
    except (KeyError, ValueError, psutil.Error):
        parent = None
    stop_file = folder / "stop"
    model.train()
    order: list[int] = []
    losses: list[float] = []
    t0 = time.time()
    for step in range(1, steps + 1):
        if stop_file.exists():
            say(stage="stopped", message="Stopped")
            return
        if parent and step % 10 == 0 and not parent.is_running():
            return
        total = 0.0
        for _ in range(accumulate):
            if not order:
                order = random.sample(range(len(data)), len(data))
            ids, labels = data[order.pop()]
            x = torch.tensor([ids], device=device)
            y = torch.tensor([labels], device=device)
            with torch.autocast("cuda", dtype=dtype):
                loss = model(input_ids=x, labels=y).loss / accumulate
            loss.backward()
            total += loss.item()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        optimizer.step()
        schedule.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(total)
        if step % 5 == 0 or step == steps:
            per_step = (time.time() - t0) / step
            say(stage="training", step=step, steps=steps, loss=round(sum(losses[-20:]) / len(losses[-20:]), 4),
                seconds_left=round(per_step * (steps - step)))
        if not math.isfinite(total):
            raise RuntimeError("Training became unstable (the loss stopped being a number). Try fewer steps.")

    # Save the LoRA, then turn it into an adapter llama.cpp loads next to the GGUF model.
    say(stage="saving", message="Saving what it learned")
    model.eval()
    adapter = folder / "adapter"
    model.save_pretrained(adapter)
    convert(run, folder, strength=1.0)
    train_peak = max(torch.cuda.max_memory_allocated(i) for i in range(torch.cuda.device_count()))
    del optimizer, model, params
    import gc

    gc.collect()
    torch.cuda.empty_cache()
    gguf = matching_gguf(run)

    # Replies from the GGUF model it will run on, with and without the LoRA, so the difference can be judged at once.
    # A LoRA learned from few examples can be too strong for a model compressed to a few bits (it loops, or leaks
    # template markers): then it's turned down until the replies are sound, and saved at that strength.
    say(stage="samples", message="Writing sample replies")
    prompts = (run.get("sample_prompts") or VOICE_PROMPTS)[:3]
    with LlamaServer(run, gguf, folder / "lora.gguf") as server:
        before = [server.reply(p, 0.0) for p in prompts]
        for strength in (1.0, 0.75, 0.5):
            after = [server.reply(p, strength) for p in prompts]
            if not any(broken(a) for a in after):
                break
    if strength != 1.0:
        convert(run, folder, strength=strength)
    replies = [{"prompt": p, "after": a, "before": b} for p, a, b in zip(prompts, after, before)]
    (folder / "samples").mkdir(exist_ok=True)
    (folder / "samples" / "replies.json").write_text(json.dumps(replies, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    say(stage="done", message="Done", seconds=round(time.time() - started), strength=strength,
        peak_gb=round(train_peak / 1e9, 1), gguf=str(gguf))


def matching_gguf(run: dict) -> Path:
    """The GGUF the trained model runs on: made here from the original it trained on, compressed the same way as the
    installed one (run["quant"]). A published GGUF can come from slightly different weights than its original's repo
    serves now (Qwen's Qwen3-8B Q4_K_M, for one), and a LoRA learned on one set of weights can then fail on the other:
    with that file, a LoRA that ends its replies with certainty in every other copy rambled on instead. Made once per
    original and compression, and shared by every run trained from it."""
    quant = run["quant"]
    dest = Path(run["matched_path"])
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    say(stage="saving", message="Making a copy of the chat model that matches what it learned on (once)")
    conv = Path(run["converter"])
    env = {**os.environ, "PYTHONPATH": str(conv / "gguf-py") + os.pathsep + os.environ.get("PYTHONPATH", ""),
           "PYTHONIOENCODING": "utf-8"}
    direct = {"BF16": "bf16", "F16": "f16", "F32": "f32", "Q8_0": "q8_0"}
    first = dest.with_name(dest.name + (".partial" if quant in direct else ".bf16.partial"))

    def run_step(cmd: list[str], what: str) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
                                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        if result.returncode != 0:
            print(result.stdout[-3000:], result.stderr[-3000:], file=sys.stderr)
            raise RuntimeError(f"Training worked, but {what} failed: "
                               + (result.stderr.strip().splitlines() or ["no details"])[-1][:300])

    try:
        run_step([sys.executable, str(conv / "convert_hf_to_gguf.py"), run["original_path"], "--outtype",
                  direct.get(quant, "bf16"), "--outfile", str(first)], "making the chat model's copy")
        if quant not in direct:
            quantize = Path(run["llama_server"]).with_name("llama-quantize" + (".exe" if os.name == "nt" else ""))
            second = dest.with_name(dest.name + ".partial")
            run_step([str(quantize), str(first), str(second), quant], f"compressing it to {quant}")
            second.replace(dest)
        else:
            first.replace(dest)
    finally:
        first.unlink(missing_ok=True)
    return dest


def convert(run: dict, folder: Path, strength: float) -> None:
    """adapter/ (peft) to lora.gguf with llama.cpp's converter. The strength is built in, as LoRA's alpha, so the
    model starts with a plain --lora."""
    adapter = folder / "adapter"
    config = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
    config["lora_alpha"] = 2 * int(run["rank"]) * strength
    (adapter / "adapter_config.json").write_text(json.dumps(config, indent=2))
    out = folder / "lora.gguf"
    conv = Path(run["converter"])
    env = {**os.environ, "PYTHONPATH": str(conv / "gguf-py") + os.pathsep + os.environ.get("PYTHONPATH", ""),
           "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, str(conv / "convert_lora_to_gguf.py"), str(adapter), "--base",
                             run["original_path"], "--outtype", "f16", "--outfile", str(out)],
                            capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not out.exists():
        print(result.stdout[-3000:], result.stderr[-3000:], file=sys.stderr)
        raise RuntimeError("Training worked, but turning the result into a llama.cpp adapter failed: "
                           + (result.stderr.strip().splitlines() or ["no details"])[-1][:300])


def broken(reply: str) -> bool:
    """Signs a LoRA is too strong: template markers in the reply, the same phrase over and over, or nothing."""
    if len(reply.strip()) < 2 or any(m in reply for m in ("<think>", "</think>", "<|", "|>")):
        return True
    words = reply.lower().split()
    grams = [" ".join(words[i:i + 5]) for i in range(len(words) - 4)]
    return any(grams.count(g) >= 3 for g in set(grams))


class LlamaServer:
    """llama-server with the GGUF model and the new LoRA, for the samples, on the cards this process can see."""

    def __init__(self, run: dict, gguf: Path, lora: Path):
        import secrets
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.token = secrets.token_urlsafe(16)
        self.cmd = [run["llama_server"], "--model", str(gguf), "--lora", str(lora), "--host", "127.0.0.1",
                    "--port", str(self.port), "--ctx-size", "4096", "--jinja", "--no-webui"]
        self.env = {**os.environ, "LLAMA_API_KEY": self.token}
        self.proc = None

    def __enter__(self):
        import httpx

        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.proc = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     cwd=str(Path(self.cmd[0]).parent), **flags)
        deadline = time.time() + 600
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("Training worked, but the chat model wouldn't start to try it out.")
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError("Training worked, but the chat model took too long to start to try it out.")

    def reply(self, prompt: str, strength: float) -> str:
        import httpx

        r = httpx.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", timeout=300,
                       headers={"Authorization": f"Bearer {self.token}"},
                       json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 200, "seed": 1234,
                             "chat_template_kwargs": NO_THINKING, "lora": [{"id": 0, "scale": strength}]})
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait()


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except Exception as e:  # report every failure to wanna.sh as a message it can show
        import traceback

        traceback.print_exc(file=sys.stderr)
        text = str(e)
        if "out of memory" in text.lower():
            text = ("The graphics card ran out of memory. Stop other models, use shorter examples, or choose a "
                    "smaller chat model.")
        say(stage="error", message=text[:600])
        sys.exit(1)
