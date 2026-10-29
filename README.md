# wanna.sh

Run AI models on your own computer: chat, pictures, video, read-aloud, transcription and music, from one friendly web app with an OpenAI-compatible API.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/surajkumar/wanna.sh/main/install.sh | bash
wanna    # then open http://localhost:7860
```

Linux, macOS, or Windows with WSL2. Needs git and Node.js 20.9+; the installer sets up Python with uv. Run it again to
update; `--chat-only` skips the AI libraries for pictures, video, voices and music. Full guide, tutorials and API docs:
https://surajkumar.github.io/wanna.sh/ (source in `site/`).

## Docker

```bash
mkdir -p ~/.wanna && docker compose up -d     # http://localhost:7860
```

Needs the NVIDIA Container Toolkit for GPUs. Code is off in Docker by default; `docker-compose.code.yml` turns it on by
mounting the Docker socket, which is root-equivalent on the host. Read the Docker guide's security section first:
https://surajkumar.github.io/wanna.sh/docs/start/docker/

## Run it by hand

```bash
# Backend (Python 3.11+, uv)
cd backend
uv venv && uv pip install -e ".[ml]"

# Frontend (Node 20+)
cd ../frontend
npm install && npm run build

# Start (serves the UI and API on one port)
cd ../backend
.venv/bin/python -m wanna            # http://localhost:7860
.venv/bin/python -m wanna --host 0.0.0.0   # reachable from your network; turn on "Require API key" first
```

For frontend development, run `npm run dev` in `frontend/` (it talks to the backend at `NEXT_PUBLIC_API_BASE`, see
`.env.development`). The dev server is a different origin, so start the backend with
`WANNA_CORS=http://localhost:3000 .venv/bin/python -m wanna`; by default wanna.sh refuses requests from other sites.

Security model (browser protection, API keys, the Code sandbox, Docker): https://surajkumar.github.io/wanna.sh/docs/reference/security/

Data lives in `~/.wanna` (models, outputs, logs, settings). Override with `WANNA_HOME`.

## How it works

- **Models** are found on Hugging Face (`/api/hub/*`), sorted into plain-language tasks, and downloaded with only the files they need. Downloads resume after a restart and restart themselves if they stall.
- **Get models** (`wanna/catalog.py`) lists every model wanna.sh can run and rates each against this computer's total graphics and system memory: *Runs great* (fits one card), *Runs well* (shared across cards), *Runs, but slowly*, or *Too big*. Voice, transcription and music models are limited to model types verified end to end (`VERIFIED_TYPES`); add a type only after generating real output with it. Models run on real hardware are marked *Tested* (`TESTED`).
- **Each loaded model runs in its own process**, pinned to its GPU(s) with `CUDA_VISIBLE_DEVICES`:
  - Chat models (GGUF) run on a prebuilt `llama-server` (llama.cpp) that wanna.sh downloads for your OS and CUDA driver. Multi-GPU uses `--tensor-split` weighted by free memory.
  - Picture, video, voice, transcription and music models run in a Python worker (`wanna/workers/runner.py`) on diffusers / transformers. Multi-GPU uses diffusers' `device_map="balanced"`.
- **Placement** (`wanna/gpu.py`, `wanna/workers/manager.py`): automatic mode puts a model on the smallest GPU that fits, splits it across GPUs if needed, unloads idle models to make room, and falls back to CPU offload only when there is enough system RAM. A RAM guard stops a worker before the machine runs out of memory.

## API

OpenAI-compatible under `/v1`: `chat/completions`, `completions`, `images/generations`, `images/edits`, `audio/speech`, `audio/transcriptions`, `audio/translations`, `videos` (async, like OpenAI's), `models`. Use `model: "auto"` to pick whatever is running. Interactive docs at `/docs`. API keys are managed under **API & apps** in the UI.
