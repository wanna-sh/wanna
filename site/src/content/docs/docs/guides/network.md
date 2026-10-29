---
title: Share wanna.sh on your network
description: Use wanna.sh from other devices, and protect it with API keys.
---

By default wanna.sh only accepts connections from the computer it runs on. You can open it to other devices on your
home or office network, for example to chat from a laptop while the models run on a desktop with a big graphics card.

## 1. Turn on API keys first

Anyone who can reach wanna.sh can use your models, so protect it before you share it:

1. Open **API & apps**, type what the key is for (for example *Laptop* or *Home Assistant*) and press **Create**.
2. Copy the key straight away. It's shown only once; wanna.sh stores only a fingerprint of it.
3. In **Settings**, turn on **Require API key**.

From then on, every request to `/v1` and `/api` needs a key, sent as either header:

```text
Authorization: Bearer wanna-...
X-API-Key: wanna-...
```

The wanna.sh interface itself keeps working without a key when you open it on the same computer.

## 2. Listen on your network

Start wanna.sh with `--host 0.0.0.0`:

```bash
wanna --host 0.0.0.0
```

Other devices can now reach it at `http://<this-computer's-address>:7860`. If you start it this way without **Require
API key** turned on, wanna.sh prints a warning.

:::caution
- The connection is plain HTTP, not encrypted. Only share wanna.sh on networks you trust, and never expose port 7860
  directly to the internet. For remote access, use a VPN such as WireGuard or Tailscale, or a reverse proxy with HTTPS.
- The interface in a browser on another device sends no API key, so with **Require API key** on, use the API (or an app
  that sends a key) from other devices.
:::

### Windows (WSL2)

WSL2 forwards `localhost` to Windows automatically, but reaching it from *other* devices needs extra setup, such as
WSL's [mirrored networking mode](https://learn.microsoft.com/windows/wsl/networking#mirrored-mode-networking) and a
Windows firewall rule for port 7860.

## Removing a key

Delete a key in **API & apps** and apps using it stop working immediately.
