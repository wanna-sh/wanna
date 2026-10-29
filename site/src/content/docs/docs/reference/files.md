---
title: Files, folders and options
description: Where wanna.sh keeps its data, its command options and environment variables.
---

## Where things are

Everything wanna.sh downloads or makes lives in one data folder, `~/.wanna` by default:

| Path | What's in it |
| --- | --- |
| `models/` | Downloaded models. |
| `outputs/` | Pictures, videos, recordings and music you've made. Also served at `http://localhost:7860/files/`. |
| `uploads/` | Files you've attached or uploaded. |
| `projects/` | [Code](/docs/tutorials/code/) projects, one folder each. |
| `knowledge/` | The original files in your [Knowledge](/docs/tutorials/knowledge/) libraries, one folder per library. |
| `code/` | Code conversations and project settings. |
| `engines/` | The chat engine (llama.cpp) wanna.sh downloaded for your system. |
| `searxng/` | Settings for the private search engine Code uses. |
| `logs/` | A log per running model, useful when one won't start. |
| `wanna.db` | The list of installed models, your gallery, Knowledge libraries and their passages, and API keys (stored as fingerprints, not the keys themselves). |
| `settings.json` | Your settings. |

Chats from the Chat page are stored in your browser, not here.

The app itself is installed in `~/wanna.sh` (or wherever you chose with `--dir`), with the `wanna` command linked from
`~/.local/bin`.

## Command options

```text
wanna [--host HOST] [--port PORT] [--reload]
```

| Option | Default | What it does |
| --- | --- | --- |
| `--host` | `127.0.0.1` | The address to listen on. `0.0.0.0` lets other devices connect; see [Share on your network](/docs/guides/network/). |
| `--port` | `7860` | The port for the app and API. |
| `--reload` | off | Restart when the code changes. For development. |

## Environment variables

| Variable | What it does |
| --- | --- |
| `WANNA_HOME` | Use a different data folder instead of `~/.wanna`. |
| `HF_TOKEN` | A Hugging Face token, used when none is saved in Settings. |
| `WANNA_CORS` | Web origins allowed to call the API from a browser, comma separated (for example `http://localhost:3000`). None by default. See [Security](/docs/reference/security/#protection-from-websites). |
| `WANNA_ALLOWED_HOSTS` | Extra host names wanna.sh answers to, comma separated (for example `mypc.local`). `localhost`, IP addresses and single-word names always work. |
| `WANNA_UI_DIR` | Serve the interface from a different folder (the built `frontend/out` by default). |
| `WANNA_LLAMACPP_TAG` | Use a different llama.cpp release than the tested one. |
| `WANNA_SANDBOX_IMAGE` | Use a different Docker image for Code's sandbox. |

These are set by the Docker image and compose files; see [Run in Docker](/docs/start/docker/):

| Variable | What it does |
| --- | --- |
| `WANNA_IN_DOCKER` | Set inside the image. Changes the startup message about network access. |
| `WANNA_HOST_HOME` | With Code on in Docker: the data folder's path on the host, for the sandbox's folder mounts. |
| `WANNA_DOCKER_NETWORK` | With Code on in Docker: the network wanna.sh shares with its sandbox and search containers. Requests from it are refused. |
