---
title: Run in Docker
description: Run wanna.sh in a container, with your graphics cards, and optionally with Code. Includes what each option means for security.
---

wanna.sh can run in a Docker container instead of being installed directly. Your models, pictures and settings live in
a folder on your computer, so you can update or remove the container without losing anything.

:::tip[Which should I choose?]
The [normal install](/docs/start/install/) is simpler and includes Code with no extra setup. Choose Docker if you
already run your services in containers, or want to keep wanna.sh and its dependencies separate from your system.
Without Code, Docker is also the more contained option. Turning Code on in Docker has security trade-offs, explained in
[Turning on Code](#turning-on-code).
:::

## What you need

- **Docker**: [Docker Engine](https://docs.docker.com/engine/install/) on Linux, or
  [Docker Desktop](https://docs.docker.com/desktop/) on Windows (with the WSL2 backend).
- **For your graphics card (NVIDIA only):**
  - Linux: the NVIDIA driver and the
    [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  - Windows: an NVIDIA driver on Windows and Docker Desktop's WSL2 backend; Docker Desktop
    [passes the GPU through](https://docs.docker.com/desktop/features/gpu/).
- **Disk space:** the full image is about 3.5 GB to download and 7 GB once unpacked (mostly PyTorch with CUDA), plus
  your models.

:::caution[macOS]
Containers on a Mac can't use the Apple GPU, so everything would run on the processor. On a Mac, use the
[Mac app](/docs/start/install/#mac-download-the-app) instead.
:::

## Quick start

```bash
git clone https://github.com/wanna-sh/wanna.git
cd wanna
mkdir -p ~/.wanna
docker compose up -d
```

Open **http://localhost:7860**. The first start downloads the image (about 3.5 GB), so give it a few minutes. Then
continue with [your first chat](/docs/start/first-chat/).

Useful commands, run in the `wanna` folder:

| Command | What it does |
| --- | --- |
| `docker compose logs -f` | Watch wanna.sh's log. |
| `docker compose down` | Stop it. Your data stays in `~/.wanna`. |
| `docker compose pull && docker compose up -d` | Update to the newest image. |

### Without Docker Compose

```bash
mkdir -p ~/.wanna
docker run -d --name wanna --gpus all \
  --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:7860:7860 \
  -v ~/.wanna:/data \
  ghcr.io/wanna-sh/wanna:latest
```

## Settings for the container

`docker-compose.yml` reads these from your environment, or from a `.env` file next to it:

| Variable | Default | What it does |
| --- | --- | --- |
| `WANNA_DATA` | `~/.wanna` | The data folder on your computer: models, outputs, settings, projects. Use an absolute path. |
| `WANNA_UID`, `WANNA_GID` | `1000` | The user and group wanna.sh runs as. Set them to yours (`id -u`, `id -g`) so the files it creates belong to you. |

For example, a `.env` file:

```bash
WANNA_DATA=/srv/wanna
WANNA_UID=1000
WANNA_GID=1000
```

The data folder must exist before you start, and be writable by that user. If it isn't, the container stops with a
message saying so.

:::note
`~/.wanna` is the same folder a normal install uses, so you can switch between Docker and a normal install and keep
your models. Don't run both at the same time on the same folder.
:::

### Images

| Image | What's in it |
| --- | --- |
| `ghcr.io/wanna-sh/wanna:latest` | Everything. |
| `ghcr.io/wanna-sh/wanna:latest-chat` | Chat and Code only, without the AI libraries for pictures, video, voices and music. Several GB smaller. |

Each release is also published by version, for example `0.1.0` and `0.1` (and `0.1.0-chat`, `0.1-chat`). To build the image yourself instead, run
`docker compose build`, or `docker build --build-arg WITH_ML=0 .` for the chat-only image.

### No NVIDIA graphics card

Delete the `deploy:` section from `docker-compose.yml` (or leave out `--gpus all`). Everything runs on the processor,
which is much slower.

## Network access

`docker-compose.yml` publishes wanna.sh as `127.0.0.1:7860`, so only programs on your own computer can reach it. Keep it
that way unless you need otherwise, and read this first:

- Inside the container, wanna.sh has to listen on all addresses (`0.0.0.0`). What protects it is the `127.0.0.1:`
  part of the port mapping. Writing just `7860:7860` makes it reachable from your network, **and Docker's port
  publishing goes around firewalls such as ufw** on Linux
  ([Docker's explanation](https://docs.docker.com/engine/network/packet-filtering-firewalls/)).
- With no API key required, anyone who can reach the port can use your models, see everything you've made, change
  settings and, if Code is on, run commands in its sandbox.
- In Docker, wanna.sh can't tell that your browser is on the same computer: Docker's networking changes where requests
  appear to come from. So if you turn on **Require API key**, the web interface stops working too, because the
  browser can't send a key. Use **Require API key** in Docker only if you use wanna.sh through its API.

To use wanna.sh from other devices, prefer a VPN (such as WireGuard or Tailscale) or a reverse proxy with HTTPS and its
own login in front of `127.0.0.1:7860`, rather than publishing the port on your network. See also
[Share on your network](/docs/guides/network/#behind-a-reverse-proxy).

Other containers can use wanna.sh by its container name, for example `http://wanna:7860/v1` from an app on the same
Docker network. To use other names or browser-based apps, set `WANNA_ALLOWED_HOSTS` or `WANNA_CORS` under
`environment:` in `docker-compose.yml`; see [Security](/docs/reference/security/#protection-from-websites).

## Turning on Code

[Code](/docs/tutorials/code/) runs the agent's commands in a separate Docker container (the sandbox), and its web search
uses another container (SearXNG). When wanna.sh itself runs in Docker, it needs to ask your computer's Docker to start
those containers, so **Code is off by default** in Docker.

### What turning it on means

Turning Code on mounts your computer's Docker socket (`/var/run/docker.sock`) into the wanna.sh container.
**Access to the Docker socket is equivalent to root access on your computer**: anything that can use it can start a
container that mounts your whole disk. Docker's own documentation
[says the same](https://docs.docker.com/engine/security/#docker-daemon-attack-surface).

In practice:

- **wanna.sh itself** can control your computer's Docker. It only uses it to start, stop and run commands in its own
  sandbox and search containers, but a security bug in wanna.sh, or in a library it uses, would become a way to take
  over your computer, not just the container.
- **Anyone who can use wanna.sh** (see [Network access](#network-access)) can create Code projects and run commands in
  the sandbox. That is the same as a normal install, but it makes keeping port 7860 private more important.
- **The agent's sandbox does not get the Docker socket.** Commands the agent runs stay inside the sandbox container,
  which only sees its project folder. The socket is only inside the wanna.sh container.
- **The sandbox can't reach wanna.sh.** wanna.sh and the sandboxes share a Docker network (`wanna-code`) so wanna.sh
  can reach them. Two separate protections stop it going the other way: each sandbox's firewall blocks private
  addresses, including the wanna.sh container and your computer, and wanna.sh also refuses every request that comes
  from the `wanna-code` network. Code running in a sandbox can't use wanna.sh's API to reach Docker.

A Docker "socket proxy" that only allows some API calls doesn't help much here: Code needs to create containers, and
being allowed to create containers is already enough to take over the computer.

How does this compare with a normal install? There, wanna.sh starts its sandboxes with your own account's Docker
access. If your account can use Docker (it's in the `docker` group, or you use Docker Desktop), that access is also
equivalent to root, so a security bug in wanna.sh would matter in a similar way. Turning Code on in Docker doesn't
create a new kind of risk; it removes the extra wall that running wanna.sh in a container would otherwise give you.

:::tip[Reducing the risk]
- Keep port 7860 bound to `127.0.0.1`, as in the default setup.
- On Linux, consider [rootless Docker](https://docs.docker.com/engine/security/rootless/). Then Docker access means
  your own user's access rather than root's. Check NVIDIA's documentation for using GPUs with rootless Docker.
- If you don't need Code, leave it off.
:::

### How to turn it on

1. Find the group that owns the Docker socket:

   ```bash
   stat -c %g /var/run/docker.sock
   ```

2. Start wanna.sh with both compose files, passing that group:

   ```bash
   export DOCKER_GID=$(stat -c %g /var/run/docker.sock)
   docker compose -f docker-compose.yml -f docker-compose.code.yml up -d
   ```

   Or put `DOCKER_GID=...` in your `.env` file.

`docker-compose.code.yml` adds three things to the wanna.sh container:

| Setting | Why |
| --- | --- |
| The Docker socket, plus `DOCKER_GID` as an extra group | So wanna.sh can start the sandbox and search containers. |
| `WANNA_HOST_HOME` (your data folder's path on your computer) | Your computer's Docker mounts project folders into the sandbox, so it needs their real path, not the path inside the wanna.sh container. This is why the data folder must be a folder on your computer, not a named Docker volume. |
| The `wanna-code` network, as `WANNA_DOCKER_NETWORK` | So wanna.sh reaches the sandboxes and SearXNG by name. |

The sandbox runs as `WANNA_UID:WANNA_GID`, so files the agent creates in `~/.wanna/projects` belong to you.

### What the sandbox can reach

The same as in a normal install (see [What the sandbox can reach](/docs/tutorials/code/#what-the-sandbox-can-reach)):
the internet, but not your computer, your local network or wanna.sh. Each sandbox gets a firewall that blocks all
private and link-local addresses, so this also covers the wanna.sh container and the other containers on the
`wanna-code` network.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `wanna.sh can't write to its data folder` | Create the folder first (`mkdir -p ~/.wanna`) and set `WANNA_UID`/`WANNA_GID` to its owner. |
| `could not select device driver "nvidia"` | Install the NVIDIA Container Toolkit (Linux) or enable the WSL2 backend (Docker Desktop), or delete the `deploy:` section to run without a GPU. |
| The system check says no graphics card | Check `docker run --rm --gpus all ubuntu nvidia-smi` works. If it doesn't, the problem is the Docker GPU setup, not wanna.sh. |
| `Set DOCKER_GID to the Docker socket's group` | Run `export DOCKER_GID=$(stat -c %g /var/run/docker.sock)` before `docker compose`. |
| Code says Docker isn't running | The socket isn't usable from the container: check `DOCKER_GID`, and that `/var/run/docker.sock` exists on your computer. |
| Code's sandbox sees an empty project | `WANNA_HOST_HOME` doesn't match the real data folder. Use an absolute `WANNA_DATA`. |
