---
title: Update and uninstall
description: Keep wanna.sh up to date, or remove it completely.
---

## Update

Run the installer again. It updates the code, the app and the interface, and keeps your models, chats and settings:

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
