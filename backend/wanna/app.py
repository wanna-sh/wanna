"""FastAPI application: API routers, generated files and the bundled web UI."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .downloads import manager as downloads
from .api import native, openai
from .config import OUTPUTS_DIR
from .workers.manager import manager

log = logging.getLogger("wanna")

UI_DIR = Path(os.environ.get("WANNA_UI_DIR", Path(__file__).resolve().parents[2] / "frontend" / "out"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    downloads.resume_pending()
    yield
    manager.unload_all()


app = FastAPI(
    title="wanna.sh",
    version="0.1.0",
    description="Run chat, image, video, speech, transcription and music models locally. "
                "OpenAI-compatible endpoints live under /v1.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("WANNA_CORS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    # OpenAI clients expect {"error": {...}}; the UI reads "detail". Provide both.
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        body = {**exc.detail, "detail": exc.detail["error"]["message"]}
    else:
        body = {"detail": exc.detail, "error": {"message": str(exc.detail), "type": "error"}}
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"detail": msg, "error": {"message": msg, "type": "invalid_request_error"}}, status_code=422)


app.include_router(openai.router)
app.include_router(native.router)
app.mount("/files", StaticFiles(directory=OUTPUTS_DIR), name="files")


@app.get("/healthz")
def healthz():
    return {"ok": True}


if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
else:
    @app.get("/")
    def no_ui():
        return {
            "message": "wanna.sh API is running. The web UI hasn't been built yet: "
                       "run `npm run build` in frontend/ and restart.",
            "docs": "/docs",
        }
