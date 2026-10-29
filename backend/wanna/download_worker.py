"""Runs in a separate process for each download.

Kept free of side effects on import: the "spawn" start method re-imports this module in the child,
so importing anything that starts threads or touches shared state here would run twice.
"""

from __future__ import annotations


def download_files(repo_id: str, files: list[str], dest: str, token: str | None, q) -> None:
    import time

    from huggingface_hub import hf_hub_download
    from tqdm.auto import tqdm

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
            hf_hub_download(repo_id, f, local_dir=dest, token=token, tqdm_class=Heartbeat)
            q.put(("file", f))
        q.put(("done", None))
    except Exception as e:  # report every failure back to the parent
        q.put(("error", f"{type(e).__name__}: {e}"))
