---
title: Troubleshooting
description: The system check, and fixes for common problems.
---

## The system check

**Settings → System check** tests each part of wanna.sh on your computer. Each line is **Ready**, **Needs attention**
or **Not working**:

| Check | If it isn't ready |
| --- | --- |
| **Graphics cards** | *No NVIDIA graphics card found*: everything runs on the processor. Check the card is installed and its driver works (`nvidia-smi` in a terminal should list it). On WSL2, install the driver on Windows. |
| **Chat engine** | *Not set up yet* is normal: llama.cpp downloads itself the first time you chat. If it failed, check your internet connection and try again. |
| **Pictures, video, voices and music** | *The AI libraries aren't installed*: run the installer again without `--chat-only`. *Can't see a graphics card*: update your NVIDIA driver, then restart wanna.sh. |
| **Code sandbox** | Install or start Docker. *Being prepared* means the sandbox image is building, which happens once. |
| **Free disk space** | Delete models you don't use in **My models**, or move your [data folder](/docs/reference/files/) with `WANNA_HOME`. |
| **System memory** | Less than 16 GB works, but stick to models rated **Runs great here**. |
| **Hugging Face** | Can't reach huggingface.co: installed models still work, but finding and downloading new ones needs internet. |
| **Web search for Code** | Needs Docker for the private search engine. If the last search failed, the error is shown. |

## Common problems

### The page says "The web UI hasn't been built yet"

The interface wasn't built. Run the installer again, or by hand: `cd ~/wanna.sh/frontend && npm ci && npm run build`,
then restart wanna.sh.

### `wanna: command not found`

`~/.local/bin` isn't on your PATH. Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or `~/.zshrc`) and open a
new terminal, or run `~/wanna.sh/backend/.venv/bin/wanna` directly.

### Port 7860 is already in use

Another program (or another copy of wanna.sh) is using it. Stop it, or start wanna.sh on another port:
`wanna --port 7861`.

### A model won't start

- Look at its rating in **Get models**. If it's **Too big for this computer**, choose a smaller version.
- Stop other models in **My models** (**Stop all and free memory**) and try again.
- For chat models, choose less **Memory for conversation** under **Options**.
- **My models → Options** has the model's log, or see `~/.wanna/logs/`.

### Replies are slow

Check **My models**: if the model says part of it runs on the processor, choose a smaller version, less memory for
conversation, or a model rated **Runs great here**.

### A download stopped

Downloads resume where they left off, including after a restart. If one stays stuck, cancel it and start it again.

### WSL2 stops suddenly while a big model runs

WSL2 ran out of memory. Use models that fit on your graphics card, or give WSL2 more memory in `.wslconfig`
([Microsoft's guide](https://learn.microsoft.com/windows/wsl/wsl-config)).

## Still stuck?

[Open an issue on GitHub](https://github.com/surajkumar/wanna.sh/issues) with what you did, what happened, and the
output of the system check.
