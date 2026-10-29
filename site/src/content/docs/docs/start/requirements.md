---
title: Requirements
description: What your computer needs to run wanna.sh, and what to expect on different hardware.
---

wanna.sh runs on most modern computers, but AI models are demanding. The more graphics memory you have, the bigger and
faster the models you can use. The app rates every model for your computer before you download it, so you never have
to guess.

## Operating system

| System | Status |
| --- | --- |
| **Linux** (x86-64) | Supported. |
| **Windows 10 or 11** (64-bit) | Supported, with the [Windows app](/docs/start/install/#windows-download-the-app). Also runs inside [WSL2](https://learn.microsoft.com/windows/wsl/install) for people who prefer the command line. |
| **macOS 14 or newer**, Apple Silicon (M1 or newer) | Supported, with the [Mac app](/docs/start/install/#mac-download-the-app). Chat runs on the Mac's GPU with Metal. Pictures, video, voices, transcription and music use the GPU on macOS 15 or newer, and the processor on macOS 14. |
| **macOS**, Intel | Chat and Code, with the [install command](/docs/start/install/#macos-from-the-command-line), on the processor. PyTorch, which pictures, video, voices and music need, isn't made for Intel Macs any more. |

:::note
wanna.sh is young, and it has been tested most on Windows (the app and WSL2) with NVIDIA graphics cards. The Mac app is
tested automatically on Apple Silicon, but pictures, video and sound on a Mac's GPU are newer and less tested. If something doesn't
work on your system, please [open an issue](https://github.com/wanna-sh/wanna/issues).
:::

## Graphics card

An **NVIDIA graphics card** is strongly recommended. Without one, everything still works but runs on the processor,
which can be 10 to 50 times slower.

Graphics memory (VRAM) decides which models fit. For chat models, a rule of thumb: a model compressed to 4 bits
needs a little over half a gigabyte per billion parameters, plus some memory for the conversation. So an 8B model fits
on an 8 GB card, and a 27B model needs roughly 16 to 20 GB.

wanna.sh can share one model across several graphics cards, so their memory adds up. For example, on a computer with an
RTX 3070 (8 GB) and an RTX 3060 (12 GB), a 27B chat model runs across both cards at about 20 tokens (roughly 15 words)
a second, and a 3B model at about 60.

You don't have to work any of this out yourself: [Get models](/docs/guides/models/) rates each model for your
computer.

Keep your NVIDIA driver up to date. After installing, the [system check](/docs/reference/troubleshooting/#the-system-check)
in **Settings** tells you whether the AI libraries can use your graphics card.

## Memory and disk

- **System memory (RAM):** 16 GB or more is recommended. Models that don't fully fit on the graphics card spill into
  system memory.
- **Disk space:** about 10 GB for the app and its AI libraries, plus space for models. Document search needs a small
  search model (about 640 MB) and room for your documents. Small models are 1 to 5 GB;
  big ones are 15 to 30 GB or more each.

## Software

**The Windows and Mac apps need nothing else.** They set up everything they use by themselves.

On Linux, and on a Mac from the command line, the [install command](/docs/start/install/#linux-one-command) checks for these and tells
you what's missing:

- **git**
- **Node.js 20.9 or newer**, to build the app's interface. Get it from [nodejs.org](https://nodejs.org) or with
  [nvm](https://github.com/nvm-sh/nvm).
- **curl**

The installer sets up Python itself, using [uv](https://docs.astral.sh/uv/).

**Optional:** [Docker](https://docs.docker.com/get-started/get-docker/) is needed only for [Code](/docs/tutorials/code/),
which runs the agent's commands inside a Docker container. On Windows, use Docker Desktop (with WSL integration turned on
if you run wanna.sh in WSL2).

## Internet

You need a connection to install wanna.sh and download models. After that, models work offline.
