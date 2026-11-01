# Changelog

Each version's section becomes its GitHub release notes (see `.github/workflows/release.yml`).

## Unreleased

- **Your own tools.** Write a Python function on the new **Tools** page (or as a file in `~/.wanna/tools`) and the AI
  can use it: in Chat with the new **Tools** switch, in Code alongside the agent's own tools, and from apps by adding
  `"wanna_tools": true` to a chat request. The function's docstring tells the model what it does and its type hints
  what to give it; packages come from the standard `# /// script` block. Test a tool with your own inputs before the
  AI uses it.
- Tools run in a Docker sandbox (the internet, but not your files, your local network or other tools). One you trust
  can run directly on this computer instead; editing it takes the trust away, and in Code the agent asks before using
  it.

## 0.4.0 (2026-10-31)

- **Chat models bigger than memory.** Turn on **Settings → Run models bigger than memory** and chat models bigger than
  your graphics and system memory together run by reading from your drive as they write, the way llama.cpp maps a
  model file. It's very slow, and works best with mixture-of-experts models such as Kimi K3 or DeepSeek, which read
  only a few of their experts for each token. Get models rates these **Runs from your drive, very slowly** whether
  or not the setting is on (saying how to turn it on), and before you download one you have to confirm you understand.
  Models with large tables llama.cpp reads a little at a time (such as Qwen3.8 Flash Next) are judged by what they
  really keep in memory, so they aren't mistaken for models that need the drive.
- **Speed estimates before you download.** For chat models, the version you pick shows how fast it will write on this
  computer, worked out from the model's own file (read from Hugging Face without downloading it) and measured speeds
  of your graphics cards, memory and drive. For a model that reads from the drive, it also says how long reading your
  message and starting take. **My models** shows the same under **Options**.
- **Compression is explained.** Chat versions show their bits per weight, and picking a heavily compressed one (below
  3 bits) says what that costs. Versions such as TQ1_0 and Q1_0 are now recognised as Tiny.
- Downloads that don't fit in the free space on your drive are refused up front, saying how much room they need.

Running from the drive was tested on Windows with NVIDIA graphics cards and under WSL2 (from WSL's own disk and from
a Windows drive), with Qwen3-30B-A3B at full precision (61 GB on a PC with 32 GB of memory). It hasn't been tested on
Macs or on Linux outside WSL yet, where estimates may be off. Estimates for models as big as Kimi K3 are worked out,
not measured.

### Fixes

- The memory guard could stop a model that was only reading its file from the drive: on Linux it counted the file's
  pages as the model's own memory, and on Windows it counted memory the graphics driver had reserved but never used.
- A mixture-of-experts chat model too big for one graphics card could be put on the smallest card alone, with most
  of its experts left on the processor, when sharing it across cards was faster. It's now shared: Qwen3-30B-A3B at
  full precision went from 3 to about 4.7 tokens a second on an 8 GB and a 12 GB card.
- The speed **My models** measured for a chat model could be how fast it read a long message rather than how fast it
  wrote, which for models that run partly on the processor is often much higher.
- Mixture-of-experts chat models too big for the graphics cards could run out of graphics memory: wanna.sh passed
  llama.cpp's planned layer count without the plan's choice of which experts stay with the processor. Both are passed
  now.

## 0.3.4 (2026-10-30)

- wanna.sh is now copyright Wannaverse. The app's footer links to [wannaverse.com](https://wannaverse.com), and it's
  still open source under the MIT licence.

## 0.3.3 (2026-10-29)

- **Chat can search the web.** With **Web** on, models that can use tools search the web and read pages when a
  question needs current or specific information, show what they're doing, and list the pages they read. It's on by
  default and can be turned off per chat.

## 0.3.2 (2026-10-29)

- **The desktop apps update themselves.** When a new version is out, the Windows and Mac apps offer to install it
  when they start, then reopen. Updates are signed and checked before they're installed. Apps from 0.3.1 or earlier
  need one last update by hand.

## 0.3.1 (2026-10-29)

### Improvements

- **Downloads carry on in the background.** While a model downloads, wanna.sh keeps the computer from going to sleep
  (the screen still locks and turns off as usual), and if the connection drops, for example when the computer wakes
  up, it tries again by itself instead of failing.
- **Saving says so.** Save buttons show "Saved" for a moment, so one click makes one copy.
- **Logs you can share.** When a model fails, its log has Copy and Save buttons.
- **Get models** shows each rating as a small gauge, and drops the "Tested" labels.

### Fixes

- Picture models downloaded in half precision (most of them, such as Stable Diffusion inpainting) failed to start on
  the processor with "no file named diffusion_pytorch_model.bin". They now load and run in full precision there.
- Big downloads on slower connections could fail with "The download kept stalling" although they were working:
  Hugging Face's downloader writes files in bursts, and long gaps looked like a stall. wanna.sh now watches the bytes
  arriving instead.
- On computers with swap, models were stopped as "ran out of system memory" while swap was still free. Free swap now
  counts, so they finish, more slowly.

## 0.3.0 (2026-10-29)

### The wanna.sh app for Mac

- **Download for Mac** (Apple Silicon, macOS 14 or newer): open the disk image, drag wanna.sh into Applications, and it
  sets itself up and opens in its own window, like the Windows app.
- **Macs use their GPU.** Chat runs on Apple's Metal (before, it ran on the processor on a Mac), and pictures, video,
  voices, transcription and music use the GPU through PyTorch on macOS 15 or newer. wanna.sh asks macOS how much memory
  the GPU may use and rates models against it. The AI libraries are about 300 MB on a Mac.

### Fixes

- On a Mac with an Intel processor, `install.sh` installs chat and Code only instead of failing: PyTorch isn't made for
  Intel Macs any more.

## 0.2.0 (2026-10-29)

### Install without a terminal

- **The wanna.sh app for Windows**: download an installer, open it, and wanna.sh sets itself up and opens in its own
  window. No terminal, git, Node.js or WSL2 needed, and no administrator rights.
- **Add-ons on demand**: chat works straight away; pictures, video, voices and music download their AI libraries the
  first time you use them, matched to your graphics card. This also works for `install.sh --chat-only` installs.

### Fixes

- The chat engine now picks the newest CUDA build your graphics driver supports. On Windows it could pick one the
  driver was too old for, and an old driver now falls back to the Vulkan build (Windows) or the processor build (Linux)
  instead of failing.
- Code's sandbox works when wanna.sh runs natively on Windows.

## 0.1.0 (2026-10-29)

The first release of wanna.sh: run AI models on your own computer, from one app.

### Make things

- **Chat** with GGUF models on llama.cpp: streaming replies, pictures for models that can see, attached documents,
  speaking instead of typing, standing instructions, and chat history with archive.
- **Pictures**, **videos**, **read aloud**, **transcribe** and **music & sound**, with diffusers and transformers.
- **Code**: a coding agent that plans, edits files, runs commands in a locked-down Docker sandbox, searches the web
  through a private SearXNG, and asks before acting (three approval modes).
- **Knowledge** (RAG): libraries of your documents, searched by meaning and by words, with numbered citations in Chat
  and a search tool in Code. Long chat attachments are searched instead of cut off.

### Models and hardware

- **Get models** lists models from Hugging Face rated for your computer, with the version that suits it, and downloads
  that resume.
- Automatic placement on the right graphics card, models shared across several cards, planned memory for chat, a
  system memory guard, and a system check in Settings.

### For developers

- An **OpenAI-compatible API** under `/v1`: chat, completions, images, speech, transcription, translation, video and
  embeddings. Plus the wanna.sh API under `/api`, with interactive docs at `/docs`.
- Optional API keys, and protection from websites (Origin, Host and CORS checks).

### Install

- A **one-line installer** for Linux, macOS and Windows (WSL2), with `--chat-only` and version pinning.
- **Docker images** on GitHub Container Registry, full and chat-only, with Code available as an option.
- Documentation and tutorials at <https://wanna.sh>.
