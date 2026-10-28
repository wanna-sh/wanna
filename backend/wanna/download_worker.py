"""Runs in a separate process for each download.

Kept free of side effects on import: the "spawn" start method re-imports this module in the child,
so importing anything that starts threads or touches shared state here would run twice.
"""

from __future__ import annotations


def download_files(repo_id: str, files: list[str], dest: str, token: str | None, q) -> None:
    from huggingface_hub import hf_hub_download

    try:
        for f in files:
            hf_hub_download(repo_id, f, local_dir=dest, token=token)
            q.put(("file", f))
        q.put(("done", None))
    except Exception as e:  # report every failure back to the parent
        q.put(("error", f"{type(e).__name__}: {e}"))
