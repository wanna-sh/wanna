---
title: Install
description: Install wanna.sh with one command on Linux, macOS or Windows (WSL2), or set it up by hand.
---

## The quick way

Open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/surajkumar/wanna.sh/main/install.sh | bash
```

The installer:

1. Checks your computer: git, curl, Node.js 20.9 or newer, and your graphics cards.
2. Installs [uv](https://docs.astral.sh/uv/) if you don't have it. uv sets up Python for wanna.sh.
3. Downloads wanna.sh to `~/wanna.sh`.
4. Installs the app and its AI libraries. **The first time, this downloads several gigabytes** (mostly PyTorch).
5. Builds the interface.
6. Adds a `wanna` command to `~/.local/bin`.

When it finishes, start wanna.sh:

```bash
wanna
```

and open **http://localhost:7860** in your browser. Next: [your first chat](/docs/start/first-chat/).

:::tip
If the installer says `~/.local/bin` isn't on your PATH, add this line to `~/.bashrc` (or `~/.zshrc` on macOS) and open
a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```
:::

### Installer options

Pass options after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/surajkumar/wanna.sh/main/install.sh | bash -s -- --chat-only
```

| Option | What it does |
| --- | --- |
| `--dir PATH` | Install somewhere other than `~/wanna.sh`. |
| `--chat-only` | Skip the AI libraries for pictures, video, voices and music. Saves several gigabytes; chat and Code still work. Run the installer again without it to add them later. |
| `--help` | Show the options. |

You can also set `WANNA_DIR` (same as `--dir`), `WANNA_BIN_DIR` (where the `wanna` command goes) and `WANNA_BRANCH`
(which branch to install).

If you'd rather read the script before running it (a good habit), download it first:

```bash
curl -fsSLO https://raw.githubusercontent.com/surajkumar/wanna.sh/main/install.sh
less install.sh
bash install.sh
```

## Windows

wanna.sh runs on Windows inside WSL2, a Linux environment built into Windows.

1. **Install WSL2.** Open PowerShell as administrator and run `wsl --install`, then restart. This installs Ubuntu by
   default. See [Microsoft's guide](https://learn.microsoft.com/windows/wsl/install) for details.
2. **Install the NVIDIA driver on Windows**, not inside Linux. The Windows driver also makes your graphics card
   available inside WSL2 ([NVIDIA's guide](https://docs.nvidia.com/cuda/wsl-user-guide/)).
3. **Install Node.js inside Ubuntu.** For example with [nvm](https://github.com/nvm-sh/nvm):
   `nvm install --lts`.
4. **Optional, for Code:** install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) and
   turn on WSL integration for your Ubuntu distribution in its settings.
5. Open the Ubuntu terminal and run the installer command above.

Open **http://localhost:7860** in your normal Windows browser; WSL2 forwards it automatically.

:::caution
WSL2 gets a share of your computer's memory (by default, half of it). Large models that spill out of the graphics card
use this memory. If WSL2 runs out, it can stop suddenly. Microsoft explains how to change the limit in
[WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config).
:::

## macOS

1. Install the Xcode command line tools for git: `xcode-select --install`.
2. Install Node.js from [nodejs.org](https://nodejs.org) or with Homebrew (`brew install node`).
3. Run the installer command above in Terminal.

## Install by hand

If you prefer to do each step yourself:

```bash
git clone https://github.com/surajkumar/wanna.sh.git
cd wanna.sh

# The app (Python 3.11 or newer)
cd backend
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[ml]"   # or -e . for chat only

# The interface (Node.js 20.9 or newer)
cd ../frontend
npm ci
npm run build

# Start it
cd ../backend
.venv/bin/python -m wanna
```

`python -m wanna` and the `wanna` command are the same thing. See [command options](/docs/reference/files/#command-options).
