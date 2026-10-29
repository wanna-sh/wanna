"""FastAPI application: API routers, generated files and the bundled web UI."""

from __future__ import annotations

import ipaddress
from importlib.metadata import version as _version
import logging
import os
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .downloads import manager as downloads
from .api import code, knowledge, native, openai
from .config import DOCKER_NETWORK, OUTPUTS_DIR
from .workers.manager import manager

log = logging.getLogger("wanna")

UI_DIR = Path(os.environ.get("WANNA_UI_DIR", Path(__file__).resolve().parents[2] / "frontend" / "out"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    downloads.resume_pending()
    from .knowledge import index as knowledge_index

    knowledge_index.resume()
    yield
    manager.unload_all()


app = FastAPI(
    title="wanna.sh",
    version=_version("wanna"),
    description="Run chat, image, video, speech, transcription and music models locally. "
                "OpenAI-compatible endpoints live under /v1.",
    lifespan=lifespan,
)

# --- Browser protection ---------------------------------------------------------------------------------
# Any web page you visit can make your browser send requests to http://localhost:7860. Three rules stop that:
# - CORS: other sites can't read wanna.sh's replies, unless their origin is listed in WANNA_CORS.
# - Origin: browsers label every cross-site request (including plain form posts, which skip CORS checks) with an
#   Origin header. Requests from another site are refused, unless listed in WANNA_CORS. Apps, scripts and SDKs
#   don't send Origin, so they're unaffected.
# - Host: a malicious site can point its own domain name at 127.0.0.1 ("DNS rebinding") to look like the same
#   site. Only localhost, IP addresses, single-word names (like a Docker container name) and names listed in
#   WANNA_ALLOWED_HOSTS are accepted.

def _env_list(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


CORS_ORIGINS = [o.rstrip("/") for o in _env_list("WANNA_CORS")]
ALLOWED_HOSTS = {h.lower() for h in _env_list("WANNA_ALLOWED_HOSTS")}


def _hostname(netloc: str) -> str:
    """'localhost:7860' -> 'localhost', '[::1]:7860' -> '::1'."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[1:netloc.find("]")] if "]" in netloc else netloc
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def _host_allowed(host: str) -> bool:
    if not host or "*" in ALLOWED_HOSTS or host in ALLOWED_HOSTS or host == "localhost" or "." not in host:
        return bool(host)
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _origin_allowed(origin: str, host_header: str) -> bool:
    if origin == "null":  # sandboxed frames and local files
        return False
    if "*" in CORS_ORIGINS or origin.rstrip("/") in CORS_ORIGINS:
        return True
    netloc = origin.split("://", 1)[-1]
    return netloc.lower() == host_header.strip().lower()  # same site; the scheme may differ behind an HTTPS proxy


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def browser_protection(request: Request, call_next):
    host_header = request.headers.get("host", "")
    if not _host_allowed(_hostname(host_header)):
        msg = (f"wanna.sh doesn't answer to the name '{_hostname(host_header)}'. If you use that name on purpose, add it "
               "to WANNA_ALLOWED_HOSTS.")
        return JSONResponse({"detail": msg, "error": {"message": msg, "type": "forbidden"}}, status_code=403)
    origin = request.headers.get("origin")
    if origin is not None and not _origin_allowed(origin, host_header):
        msg = (f"Requests from web pages on {origin} aren't allowed. If you trust that site, add it to WANNA_CORS.")
        return JSONResponse({"detail": msg, "error": {"message": msg, "type": "forbidden"}}, status_code=403)
    return await call_next(request)


# With Code turned on in Docker, wanna.sh shares a network with the Code sandboxes. Code running there must not be
# able to use wanna.sh's own API (and through it, Docker), so requests from that network are refused. Its gateway
# address is the host side of the network: Docker's port publishing (your browser) arrives from there.
_sandbox_subnets: list = []
_sandbox_gateways: set = set()
_subnets_checked = 0.0


def _sandbox_networks() -> list:
    global _sandbox_subnets, _subnets_checked
    if DOCKER_NETWORK and not _sandbox_subnets and time.time() - _subnets_checked > 30:
        _subnets_checked = time.time()
        r = subprocess.run(["docker", "network", "inspect", "-f", "{{range .IPAM.Config}}{{.Subnet}} {{.Gateway}};{{end}}",
                            DOCKER_NETWORK], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            for entry in filter(None, (e.split() for e in r.stdout.split(";"))):
                _sandbox_subnets.append(ipaddress.ip_network(entry[0]))
                if len(entry) > 1:
                    _sandbox_gateways.add(ipaddress.ip_address(entry[1]))
        else:
            log.error("Couldn't read the %s network: %s", DOCKER_NETWORK, r.stderr.strip()[-200:])
    return _sandbox_subnets


@app.middleware("http")
async def refuse_sandbox_network(request: Request, call_next):
    if DOCKER_NETWORK and request.client:
        try:
            ip = ipaddress.ip_address(request.client.host)
        except ValueError:
            ip = None
        if ip is not None and ip not in _sandbox_gateways and any(ip in net for net in _sandbox_networks()):
            msg = "wanna.sh doesn't accept requests from the Code sandbox network."
            return JSONResponse({"detail": msg, "error": {"message": msg, "type": "forbidden"}}, status_code=403)
    return await call_next(request)


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
app.include_router(knowledge.router)
app.include_router(code.router)
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
