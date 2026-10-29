---
title: Update and uninstall
description: Keep wanna.sh up to date, or remove it completely.
---

## Update

**Windows app:** download the [latest version](https://github.com/wanna-sh/wanna/releases/latest/download/wanna.sh-setup-windows-x64.exe)
and open it. It updates the app in place and keeps your models, chats and settings. Close wanna.sh first.

**Mac app:** download the [latest version](https://github.com/wanna-sh/wanna/releases/latest/download/wanna.sh-macos-arm64.dmg),
quit wanna.sh, and drag the new one into **Applications**, replacing the old one. It keeps your models, chats and
settings.

**Linux, macOS from the command line, and WSL2:** run the installer again. It updates the code, the app and the interface, and keeps your models, chats and settings:

```bash
curl -fsSL https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh | bash
```

If you installed a [specific version](/docs/start/install/#a-specific-version), this moves you to the latest one. To
switch to another version instead, add `WANNA_BRANCH=v<version>` before `bash`.

Or, from the folder you installed to, get the latest code and rebuild:

```bash
cd ~/wanna.sh
git pull
./install.sh
```

Stop wanna.sh first (press **Ctrl+C** in its terminal), and start it again with `wanna` afterwards.

Running in Docker? Run `docker compose pull && docker compose up -d` in the `wanna` folder. See
[Run in Docker](/docs/start/docker/).

## Uninstall

### Windows app

1. Open **Settings → Apps → Installed apps**, find **wanna.sh**, and choose **Uninstall**.
2. To also remove its Python and logs, delete `%LOCALAPPDATA%\sh.wanna.desktop`.
3. To remove your models, pictures and settings, delete `C:\Users\<you>\.wanna`. **This deletes every downloaded
   model and everything you've made**, so copy anything you want to keep first.
4. If you used Code, remove its Docker containers and images in Docker Desktop (their names start with `wanna-`).

### Mac app

1. Quit wanna.sh and drag **wanna.sh** from **Applications** to the Bin.
2. To also remove its Python and logs, delete `~/Library/Application Support/sh.wanna.desktop` (in the Finder, press
   **⇧⌘G** and paste the path).
3. To remove your models, pictures and settings, delete the `.wanna` folder in your home folder. **This deletes every
   downloaded model and everything you've made**, so copy anything you want to keep first.
4. If you used Code, remove its Docker containers and images in Docker Desktop (their names start with `wanna-`).

### Linux, macOS from the command line, and WSL2

1. Stop wanna.sh.
2. Remove the app and the `wanna` command:

   ```bash
   rm -rf ~/wanna.sh ~/.local/bin/wanna
   ```

3. Remove your data. **This deletes every downloaded model, picture, recording and Code project**, so copy anything you
   want to keep first:

   ```bash
   rm -rf ~/.wanna
   ```

4. If you used Code, remove its Docker containers and images:

   ```bash
   docker rm -f $(docker ps -aq --filter label=wanna.code=1) $(docker ps -aq --filter label=wanna.search=1)
   docker images | grep -E "wanna-sandbox|searxng|wanna.sh"   # then: docker rmi <image>
   ```

   If you ran wanna.sh itself in Docker, also run `docker compose down` in the `wanna` folder, and
   `docker network rm wanna-code` if you turned on Code.

Chats are stored in your browser. To remove them, use **Chat → Chats → Delete all chats** before uninstalling, or clear
the site data for `localhost:7860` in your browser.
