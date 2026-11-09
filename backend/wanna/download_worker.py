"""Runs in a separate process for each download.

Kept free of side effects on import: the "spawn" start method re-imports this module in the child,
so importing anything that starts threads or touches shared state here would run twice.
"""

from __future__ import annotations

import os
import re

# A file from another repo is written "repo::path" (a picture model's text encoder or VAE from the original release).
# It's saved under the model's folder at companions/<repo>/<path>.
SEP = "::"


def companion_dir(repo: str) -> str:
    """Folder, relative to the model's, that holds files from another repo."""
    return os.path.join("companions", re.sub(r"[^A-Za-z0-9._-]+", "--", repo))


def local_path(ref: str) -> str:
    """Where a download's file lands, relative to the model's folder."""
    if SEP not in ref:
        return ref
    repo, path = ref.split(SEP, 1)
    return os.path.join(companion_dir(repo), path)


def download_files(repo_id: str, files: list[str], dest: str, token: str | None, q, xet: bool = True) -> None:
    import time

    from huggingface_hub import constants, hf_hub_download
    from tqdm.auto import tqdm

    if not xet:  # read when each file starts, so setting it here is enough
        constants.HF_HUB_DISABLE_XET = True

    class Heartbeat(tqdm):
        """Tells the parent that bytes are arriving. Files can grow in bursts far apart (Hugging Face's Xet
        downloader writes whole chunk ranges at once), so their size alone looks like a stall on slow connections."""

        last = 0.0

        def update(self, n=1):
            now = time.monotonic()
            if n and now - Heartbeat.last >= 1:
                Heartbeat.last = now
                q.put(("progress", None))
            return super().update(n)

    try:
        for f in files:
            if SEP in f:
                repo, path = f.split(SEP, 1)
                hf_hub_download(repo, path, local_dir=os.path.join(dest, companion_dir(repo)), token=token,
                                tqdm_class=Heartbeat)
            else:
                hf_hub_download(repo_id, f, local_dir=dest, token=token, tqdm_class=Heartbeat)
            q.put(("file", f))
        q.put(("done", None))
    except Exception as e:  # report every failure back to the parent
        q.put(("error", f"{type(e).__name__}: {e}"))
