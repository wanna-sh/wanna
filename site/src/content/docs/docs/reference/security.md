---
title: Security
description: How wanna.sh protects your computer, what it trusts, and the settings that change that.
---

wanna.sh runs AI models and, with [Code](/docs/tutorials/code/), runs programs an AI writes. This page explains what
protects you, what each setting changes, and what wanna.sh does *not* protect against.

## The short version

- **Only your computer can use wanna.sh**, unless you start it with `--host 0.0.0.0` or change the Docker port
  mapping.
- **Websites you visit can't use it**, even though it runs on `localhost` and your browser can reach it.
- **Code's commands run in a locked-down Docker container** that can reach the internet, but not your computer, your
  local network or wanna.sh.
- **Nothing you make or type is sent anywhere.** wanna.sh only goes online to find and download models, download its
  chat engine and run Code's web tools.

## Who can use wanna.sh

wanna.sh has no user accounts. Anyone who can reach it can do everything it can: use your models, see everything you've
made, change settings, download models and run Code projects.

| How you run it | Who can reach it |
| --- | --- |
| `wanna` (the default) | Programs on this computer only. It listens on `127.0.0.1`. |
| `wanna --host 0.0.0.0` | Every device on your network. Turn on **Require API key** first. See [Share on your network](/docs/guides/network/). |
| Docker, default `docker-compose.yml` | Programs on this computer only (`127.0.0.1:7860`). See [Run in Docker](/docs/start/docker/#network-access). |

"Programs on this computer" includes other user accounts on a shared computer. On a shared or multi-user machine, turn on
**Require API key**.

### API keys

With **Require API key** on (Settings → Security), every request to `/v1` and `/api` needs a key from **API & apps**,
sent as `Authorization: Bearer ...` or `X-API-Key: ...`. The interface you open on the same computer keeps working
without one. Keys are stored only as fingerprints (SHA-256 hashes), so they can't be read back.

In Docker, wanna.sh can't tell that your browser is on the same computer, so with **Require API key** on the interface
stops working too. See [Run in Docker](/docs/start/docker/#network-access).

## Protection from websites

Your browser can reach anything on `localhost`, including wanna.sh, so a web page you visit could try to send it
requests. wanna.sh refuses them with three checks:

| Check | What it stops |
| --- | --- |
| **Origin** | Browsers label requests made by a web page with the page's address (its *origin*). wanna.sh refuses requests from any origin other than its own. This includes plain form posts, which browsers send without asking first. |
| **CORS** | Even if a request got through, other sites can't read wanna.sh's replies. No other origin is allowed by default. |
| **Host** | A malicious site can point its own domain name at `127.0.0.1` ("DNS rebinding") to look like wanna.sh itself. wanna.sh only answers to `localhost`, IP addresses, single-word names (such as a Docker container name) and names you list in `WANNA_ALLOWED_HOSTS`. |

Apps, scripts and SDKs (Python, JavaScript on a server, curl) don't send an origin, so these checks don't affect them.

You only need to change anything if:

- **A web app in your browser calls the wanna.sh API directly** (not through its own server). Add its origin to
  `WANNA_CORS`, for example `WANNA_CORS=https://chat.example.com`. Several are separated by commas.
- **You reach wanna.sh by a name with a dot in it**, such as `mypc.local` or `wanna.example.com` behind a reverse proxy.
  Add it to `WANNA_ALLOWED_HOSTS`, for example `WANNA_ALLOWED_HOSTS=mypc.local`.

Blocked requests get a `403` saying which setting to change.

:::caution
`WANNA_CORS=*` and `WANNA_ALLOWED_HOSTS=*` switch these protections off. Only use them if something else (such as a
reverse proxy with its own login) stands between wanna.sh and the web.
:::

## The model engines

Each loaded model runs in its own process with its own port on `127.0.0.1`. wanna.sh gives each one a random secret when
it starts, and refuses to talk to it without the secret, so other programs and web pages can't use a model directly.
The secret is passed through the environment, not the command line, so it doesn't show up in the process list. Only the
engines' status checks (`/health`) answer without it.

## Code's sandbox

Code runs everything the agent does (commands, installs, servers) in a Docker container per project. It runs as your
user ID, with no administrator rights, and sees only its project folder.

| The sandbox can reach | |
| --- | --- |
| The internet | Yes, to install packages and read documentation. |
| Its own servers (`localhost` inside the sandbox) | Yes. |
| Your computer, including wanna.sh | No. |
| Your local network | No. |
| Cloud metadata addresses (`169.254.169.254`) | No. |
| Files outside its project folder | No. |

A firewall inside each sandbox blocks all private and link-local addresses. It's set up from outside by a short-lived
helper; the sandbox itself has no permission to change network settings, so nothing the agent runs can turn it off. If
the firewall can't be set up, the sandbox doesn't start. Each sandbox is limited to 4 GB of memory, 4 processor cores
and 512 processes.

The agent's `web_fetch` tool runs inside wanna.sh, not the sandbox, and applies the same rule: it refuses local and
private addresses, checking every redirect, except the project's own preview ports.

What the sandbox does *not* protect: **the project folder itself.** The agent can change or delete anything in it, and
use the internet as it likes. **Approval** controls this: *Ask before commands* (the default) shows you every command
first, *Ask before any change* shows every edit too. Keep important work in git.

### Code and Docker access

To create sandboxes, wanna.sh uses Docker. Docker access is equivalent to administrator (root) access on your computer.
In a normal install wanna.sh uses your own account's Docker access; in Docker, turning on Code gives the wanna.sh
container the Docker socket. Either way, a security bug in wanna.sh could become a way to control your computer. See
[Turning on Code](/docs/start/docker/#turning-on-code) for the details and how to reduce the risk.

## Models from the internet

Models are downloaded from Hugging Face, and anyone can publish one, so wanna.sh treats them as data, never as code:

- **No code from model repositories runs.** wanna.sh never turns on the libraries' `trust_remote_code` option, so Python
  files that come with a model are ignored.
- **Weights in safe formats are preferred.** Chat models are GGUF files, and for other models wanna.sh downloads
  `safetensors` weights when the model has them. Neither format can contain code.
- **Older formats are loaded in a restricted mode.** A few models only have PyTorch `.bin` or `.pt` files, which use
  Python's pickle format. diffusers and transformers load these with PyTorch's *weights-only* mode, which refuses
  anything that isn't plain data.

## Privacy

- Prompts, chats, documents and everything you make stay on your computer.
- Chats are stored in your browser. Everything else is in your [data folder](/docs/reference/files/), including the
  documents you add to [Knowledge](/docs/tutorials/knowledge/), which are read and searched on this computer only.
- wanna.sh connects to Hugging Face (finding and downloading models), GitHub (downloading the chat engine), Docker Hub
  (Code's sandbox and search images) and, for Code, to the websites the agent searches and reads. Searches go through a private SearXNG on your computer, which
  forwards them to public search engines; with a Brave Search key, they go to Brave.
- wanna.sh has no telemetry or analytics of its own.

## Settings that affect security

| Setting | Default | Effect |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Who can connect. |
| **Require API key** (Settings) | Off | Require a key for the API. |
| `WANNA_CORS` | none | Web origins allowed to call the API from a browser. |
| `WANNA_ALLOWED_HOSTS` | none | Extra host names wanna.sh answers to. |
| **Approval** (per Code project) | Ask before commands | What the agent can do without asking. |
| `docker-compose.code.yml` | Not used | Turns on Code in Docker by giving wanna.sh the Docker socket. |

## Reporting a vulnerability

Please report security problems privately through the **Security** tab of the
[GitHub repository](https://github.com/wanna-sh/wanna/security), not in a public issue.
