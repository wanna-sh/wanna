# Changelog

Each version's section becomes its GitHub release notes (see `.github/workflows/release.yml`).

## Unreleased

- **wanna.sh has a Discord server.** Join it from the sidebar, the home page or the website.
- **Chat no longer fails when a small model gets a tool call wrong.** With web search (or your own tools) on, some
  small models ask for a tool in a form llama.cpp can't read (Llama 3.2 1B writes `"function": "web_search"`
  instead of `"name"`), and llama.cpp then failed the whole reply: *The model produced output that does not match
  the expected peg-native format*. Chat now asks the model again without tools, so you get an answer, with a note
  that it was made without them.
- **The Windows and Mac apps keep running in the tray.** Closing the window hides it: wanna.sh keeps running in the
  system tray (the menu bar on a Mac), so apps, other devices and reverse proxies keep working. Click the icon to open
  it again, or choose **Quit wanna.sh** from its menu to stop it and free the graphics card. The first time, a message
  says so. CI now compile-checks the desktop app on every push, not only when a release is built.
- **Settings has its own menu.** Its seven panels are now four pages, each with its own address: **This computer**
  (system check, graphics cards, engines), **Accounts** (Hugging Face, web search), **Models & memory** and
  **Security** (API key, allowed host names). Messages that send you to Settings name the page, and links go
  straight to it.
- **Linux and WSL: the picture engine for NVIDIA cards downloads ready-made.** GGUF picture models (Qwen-Image 2.1,
  Qwen-Image-Edit) no longer need the CUDA toolkit and a 10 to 20 minute build: wanna.sh downloads stable-diffusion.cpp
  built for CUDA 12 (GTX 10 series to RTX 50 series), and NVIDIA's CUDA runtime and cuBLAS from NVIDIA's packages on
  PyPI, checking each against a pinned checksum. It's built by a new workflow, `sdcpp-linux-cuda.yml`, once for each
  stable-diffusion.cpp version wanna.sh uses, and published on its own release. Building it here remains for Arm
  computers and drivers older than CUDA 12. Engines built here before keep working.
- **GGUF picture models too big for one graphics card are split across your cards.** Before, the engine drew on one
  card and copied the rest of the model onto it from system memory for every step: Qwen-Image-Edit Rapid (14 GB) on
  a 12 GB RTX 3060 took minutes a step. Now its layers are shared between the cards, with the text encoder and VAE on
  the second one so the first keeps room for changing and combining pictures: a picture in about 25 seconds, a change
  or a combination of two in about 30, on an RTX 3060 and RTX 3070.
- The picture engine's downloads go to disk instead of memory (the Windows one is about 900 MB).
- Choosing a GGUF picture model on the Pictures page starts setting up its engine straight away, with a progress bar
  saying what it's doing (and **Try again** if it fails); **Create** waits until it's ready. My models shows it too.
  If you try a model before then, the message says what's happening and how far along it is: a download on most
  computers, not "building it for your graphics card" as it said everywhere before.
- Qwen-Image 2.1 uploads with a GGUF text encoder (such as the Genesis ones) download its vision file too, which
  changing and combining pictures need. Before, only making pictures from a description worked with them.
- GGUF picture models are recognised from their files, not their names: wanna.sh reads each file's header (a few
  kilobytes) to tell the picture model, text encoder, vision file and VAE apart, and uses an upload's own parts
  only when they fit the model (the right text encoder, with its own vision file). Renamed uploads are found, and
  mismatched parts are replaced with the original release's. Lists of models stay quick: headers are read when
  you open a model or download it.
- **Qwen-Image-Edit Rapid** uploads (Phr00t's Rapid AIO and its GGUF versions) run with the settings their maker
  recommends: 4 steps, prompt strength 1, euler_a with the beta scheduler. They make pictures from a description as
  well as change pictures (up to 3 at once), and versions built on Qwen-Image-Edit-2511 (v15 and later) get its
  setting. **Quick** never goes below 4 steps for them. When an upload carries several versions of a model, wanna.sh
  offers the newest one's sizes, labelled with the version.

## 0.9.0 (2026-11-03)

- **Change pictures by describing the change.** Editing models, such as Qwen-Image-Edit (and its 2509 and 2511
  versions) and Qwen-Image 2.1, are now in **Get models → Pictures**. Attach a picture on the Pictures page, say what to
  change (*make it a snowy evening*) and press **Change**: the rest of the picture stays as it was, and the result
  keeps its shape. Qwen-Image 2.1 also makes pictures from a description. `POST /v1/images/edits` uses them too.
- **Combine several pictures.** Qwen-Image 2.1 takes up to 10 pictures at once, and Qwen-Image-Edit-2509 and -2511 up
  to 3: **Add pictures**, then describe how to combine them by number (*the person in picture 1 and the person in
  picture 2 at a café*), or give a pose map to change a person's pose. wanna.sh checks the number against the model:
  extra pictures aren't added silently, and switching to a model that takes fewer offers one that takes them all.
  `/v1/images/edits` takes several `image` (or `image[]`) fields, and `/api/generate/image` takes `image_uploads`.
- Pictures and Videos pick up a picture or video still being made when you come back to the page, and show its
  progress again. GGUF picture models show their progress in stages: getting ready, the steps, then finishing.
- **Picture models in GGUF files.** These run on a new engine, stable-diffusion.cpp, which wanna.sh sets up the first
  time it's needed. Its library is loaded into wanna.sh's own worker, so nothing new listens on a port, and it doesn't
  need the AI libraries download. A model's download includes the text encoder and VAE it needs, from the original
  release when the upload doesn't have them. Parts that don't fit on the graphics card go to system memory. On Linux
  and WSL with an NVIDIA card, wanna.sh builds the engine for your card (once) when the CUDA toolkit, cmake and git are
  installed, and otherwise uses the processor, says what to install and links to step-by-step instructions
  ([Graphics card for GGUF picture models on Linux and WSL](https://wanna.sh/docs/guides/linux-gpu-pictures/)).
  On a Mac they need macOS 26 or newer, which is what stable-diffusion.cpp is built for.
  Tested on WSL (Debian 13) with an RTX 3060 and RTX 3070: Qwen-Image 2.1 in Q8_0 made a 512 × 512 picture in under a
  minute, and combined two pictures into one. Not yet tested on Windows or Mac.
- Pillow is now installed with wanna.sh itself, not only with the AI libraries.

## 0.8.2 (2026-11-03)

- **Allowed host names in Settings.** Names with a dot in them that you open wanna.sh by, such as `mypc.local` or a
  reverse proxy's domain, can now be added under **Settings > Security > Allowed host names**, as well as with
  `WANNA_ALLOWED_HOSTS`. Names from both are allowed, and the page shows the ones set by `WANNA_ALLOWED_HOSTS`. `*`
  (which turns the check off) can still only be set with `WANNA_ALLOWED_HOSTS`.

## 0.8.1 (2026-11-01)

- Agents' programs that exit cleanly have finished: they're no longer restarted over and over as if they had crashed.
  A program that crashes wakes its agent the first time it's restarted, not every time.
- Agents are told that their programs can't use their tools (such as web search), and to use a schedule for work that
  needs them, instead of writing programs that can't work.
- Agents' schedules repeat at most every 5 minutes, so one can't wake its model every minute all day.
- The Agents page warns when an agent's model is small (under about 4B): small models struggle to work on their own.
  Chat models' sizes come from their files.
- An agent's error no longer reads "The model didn't answer: ." when the problem came without a message.

## 0.8.0 (2026-11-01)

- **Agents: an AI that runs around the clock.** The new **Agents** page runs AIs that keep working on their own toward
  goals you give them, on your own chat model. Each has a Linux sandbox of its own (the same as Code's), where it
  writes and runs programs and keeps them running as services: wanna.sh restarts them when they stop and after
  restarts. It waits until something happens, or keeps thinking if you choose **Always thinking**, and wakes for your
  messages, schedules it sets itself, files its own programs write to `/workspace/.inbox`, and a webhook link other
  apps can post to. It tells you things with notifications: on its page, as a badge in the menu, on this computer, and
  on your phone through ntfy, or in Discord or Slack. It summarises its memory when it fills and keeps notes in
  `MEMORY.md`. Secrets are given to its services as environment variables and hidden from the model. A limit on steps
  an hour, help when it repeats itself and retries after failures keep it on track, and agents that were on come back
  on when wanna.sh starts. `/api/agents` does all of this from apps.

## 0.7.0 (2026-11-01)

- **Train your own picture style.** The new **Train** page teaches a Stable Diffusion 1.5 or SDXL picture model a
  subject (a person, a pet, a thing) or a style from 3 to 50 of your pictures, on your own graphics card. Choose
  what to teach, drop in pictures, name it, and press **Start training**: it suggests a trigger word and the number of
  steps, estimates how long it will take, and shows sample pictures when it's done. **Use it in Pictures** opens
  Pictures with it chosen; afterwards pick it under **Style**, with a strength setting under **More settings**.
- **Trained styles in the API.** `/v1/images/generations` and `/api/generate/image` take `lora` (a trained style's
  id) and `lora_strength`, and `/api/training` starts, follows and manages training from apps.
- **Train a chat model.** The Train page's **Chat** side teaches a chat model your writing voice (from your writing:
  text, Markdown or PDF files, or pasted) or how to answer (from example chats: typed in, or .jsonl, .json or .csv
  files). It trains on the model's original version, downloaded once, at full precision when it fits on your
  graphics card and in 4 bits (QLoRA) when it doesn't, across several cards if needed. The result is a chat model of
  its own in Chat, Code and the API, running in llama.cpp on a copy of the model made from the same original, with
  sample replies before and after on the Train page. `/api/training/chat` starts it from apps.
- Training needs more libraries, PEFT and bitsandbytes. The Train page offers to install them if your AI libraries
  came before this version.
- **Your own AI for a task.** The new **Tasks** page teaches the AI a job of your own from examples: flag, sort or
  score things from a table (gradient-boosted trees, in seconds, no graphics card needed), sort text or pictures
  (with your search model), or write answers your way and pull details out as JSON (a trained chat model). wanna.sh
  picks the method, tests it on examples it didn't learn from, and says how well it does in plain words, next to what
  always giving the most common answer would get; for yes/no tasks, a table of how many it catches against false
  alarms sets how sure it must be. A chat model can draft missing answers for you to check. Use it on the page, on a
  whole file, from `/api/tasks`, or as a tool the AI uses in Chat and Code.
- The AI libraries install now skips libraries meant for other systems.

Tested on Windows with an RTX 3060 12 GB: Stable Diffusion 1.5 (400 steps in under 4 minutes, 3.4 GB of graphics
memory) and SDXL (400 steps in about 13 minutes, 9.8 GB at most); Llama 3.2 1B (writing voice, under 2 minutes with
its download, 2.8 GB) and Qwen3 8B in 4 bits (30 example chats, about 4 minutes, 7.0 GB). Tasks: a standard breast
tumour table (96.7% right, against 62.7% for always giving the most common answer), 600 newsgroup posts in 4 topics
(94.3%, with Qwen3 VL Embedding 2B), cat, dog and car pictures, a made-up card-fraud table, and written answers with
Llama 3.2 1B; drafting with Qwen3 8B and Gemma 4 E4B. Not yet tested on Linux. Training isn't available on Macs yet.

## 0.6.0 (2026-11-01)

- **Search pictures.** With a search model that can see pictures, such as the new suggestion **Qwen3 VL Embedding 2B**,
  Knowledge libraries take photos and screenshots, and PDFs of scanned pages (each page is read as a picture).
  Describe what you're looking for to find matching pictures, or search with a picture to find ones like it. Chat
  shows the pictures it found, and gives them to a chat model that can see.
- **Pictures in the embeddings API.** `/v1/embeddings` takes pictures as `image_url` parts (data URLs) next to text,
  for models that can see them, and `/api/knowledge/search` takes an `image` to search with.

Tested on Windows with Qwen3 VL Embedding 2B and Gemma 4 E4B, with a small library of photos, a scanned PDF and a
note. Not yet tested on Macs or Linux, or with large picture libraries.

## 0.5.0 (2026-11-01)

- **Your own tools.** Write a Python function on the new **Tools** page (or as a file in `~/.wanna/tools`) and the AI
  can use it: in Chat with the new **Tools** switch, in Code alongside the agent's own tools, and from apps by adding
  `"wanna_tools": true` to a chat request. The function's docstring tells the model what it does and its type hints
  what to give it; packages come from the standard `# /// script` block. Test a tool with your own inputs before the
  AI uses it.
- Tools run in a Docker sandbox (the internet, but not your files, your local network or other tools). One you trust
  can run directly on this computer instead; editing it takes the trust away, and in Code the agent asks before using
  it.

Tested on Windows with Docker Desktop, in Chat, Code and the API, with Gemma 4 E4B. Not yet tested on Macs or Linux.

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
