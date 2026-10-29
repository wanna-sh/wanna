# Contributing to wanna.sh

Thanks for helping! Bug reports, fixes, docs improvements and new model support are all welcome. For anything large,
open an issue first so we can agree on the approach.

Security problems: please don't open an issue. See [SECURITY.md](SECURITY.md).

## Set up

You need git, Node.js 20.9 or newer, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/wanna-sh/wanna.git
cd wanna

cd backend
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[ml]"   # or -e . to skip the AI libraries

cd ../frontend
npm ci
npm run build          # the app serves the built interface from frontend/out

cd ../backend
.venv/bin/python -m wanna   # http://localhost:7860
```

To work on the interface with live reload, run `npm run dev` in `frontend/` and start the backend with
`WANNA_CORS=http://localhost:3000 .venv/bin/python -m wanna`. To keep your test data apart from a real install, set
`WANNA_HOME` to another folder.

## Before you open a pull request

CI (`.github/workflows/ci.yml`) runs these; running them first saves a round trip:

```bash
cd backend && uvx ruff check --isolated --select E9,F wanna
cd frontend && npx eslint src && npm run build && npx tsc --noEmit
cd site && npm ci && npm run build
shellcheck install.sh docker/entrypoint.sh
```

Changes to models, placement or generation can't be checked by CI. Please say in the pull request which models and
hardware you tried them on.

## Where things are

- `backend/wanna/`: the server (FastAPI), model engines and workers, Code (`code/`) and Knowledge (`knowledge/`).
- `frontend/src/`: the interface (Next.js, built to static files).
- `site/`: the website and documentation at <https://wanna.sh> (Astro + Starlight). If you change how something
  works, update its page in `site/src/content/docs/docs/` in the same pull request.
- `install.sh`, `Dockerfile`, `docker-compose*.yml`: installing and running.

## Style

- Write for people who aren't technical: plain words in the interface and docs, and say what to do next when
  something goes wrong.
- Match the code around you. Comments explain why, not what.

## Releases

See "Releasing" in the [README](README.md#releasing).
