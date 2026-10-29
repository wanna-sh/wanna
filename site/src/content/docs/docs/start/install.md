---
title: Install
description: Download the wanna.sh app for Windows, or install it with one command on Linux and macOS.
---

## Windows: download the app

1. Download **[wanna.sh for Windows](https://github.com/wanna-sh/wanna/releases/latest/download/wanna.sh-setup-windows-x64.exe)**
   (Windows 10 or 11, 64-bit).
2. Open the file you downloaded. It installs wanna.sh for your account only, so it doesn't ask for administrator
   rights, and adds it to the Start menu.
3. wanna.sh opens in its own window. The first time, it downloads Python and its core parts, which takes a minute or
   two. After that it starts in a few seconds.

Then continue with [your first chat](/docs/start/first-chat/).

:::caution["Windows protected your PC"]
The installer isn't code-signed yet, so Windows SmartScreen may warn about it. Click **More info**, check the publisher
line reads *Unknown publisher* and the file is `wanna.sh-setup-windows-x64.exe`, then click **Run anyway**. You can
check the download first on [GitHub](https://github.com/wanna-sh/wanna/releases/latest), which builds it from the
public source code.
:::

Good to know:

- **Chat works straight away.** Pictures, video, voices and music need extra AI libraries (about 3 GB). wanna.sh offers
  to download them the first time you open one of those pages, matched to your graphics card.
- **Your graphics card:** keep the NVIDIA driver up to date. wanna.sh picks the chat engine and AI libraries that suit
  the driver you have.
- **While the window is open,** other apps can use wanna.sh's [API](/docs/api/) at `http://localhost:7860`. Closing the
  window stops wanna.sh and frees the graphics card.
- **Code** needs [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) for its sandbox.
- **Where things are:** your models, pictures and settings are in `C:\Users\<you>\.wanna`, the app in
  `%LOCALAPPDATA%\wanna.sh`, and its Python and logs in `%LOCALAPPDATA%\sh.wanna.desktop`.

## Linux and macOS: one command

Open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh | bash
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

### A specific version

The command above installs the latest version. To install a particular release instead, give its version (see
[releases](https://github.com/wanna-sh/wanna/releases)):

```bash
curl -fsSL https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh | WANNA_BRANCH=v0.1.0 bash
```

Running the installer again with another version switches to it. Running it without one updates to the latest.

### Installer options

Pass options after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh | bash -s -- --chat-only
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
curl -fsSLO https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh
less install.sh
bash install.sh
```

## Windows with WSL2

Prefer the command line? wanna.sh also runs on Windows inside WSL2, a Linux environment built into Windows. Most people
should use the [Windows app](#windows-download-the-app) instead.

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
git clone https://github.com/wanna-sh/wanna.git
cd wanna

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

## Docker

wanna.sh also runs in a container. See [Run in Docker](/docs/start/docker/).
