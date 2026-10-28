"""Start wanna.sh: `python -m wanna` or `wanna` after installing."""

from __future__ import annotations

import argparse
import logging


def main() -> None:
    ap = argparse.ArgumentParser(prog="wanna", description="Run AI models locally with a friendly web UI.")
    ap.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 to allow other devices on your network")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .config import load_settings

    if args.host not in ("127.0.0.1", "localhost") and not load_settings().get("require_api_key"):
        logging.warning(
            "wanna.sh is reachable from your network without an API key. "
            "Turn on 'Require API key' in Settings to protect it."
        )

    import uvicorn

    print(f"\n  wanna.sh is starting at http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}\n")
    uvicorn.run("wanna.app:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
