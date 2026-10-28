"""Code projects API: projects, files, and the agent (live events over Server-Sent Events)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..code import agent, projects, sandbox, tools
from .auth import require_key

router = APIRouter(prefix="/api/code", dependencies=[Depends(require_key)])


def _project(pid: str) -> dict:
    if not projects.valid_id(pid):
        raise HTTPException(404, "Project not found")
    return projects.get(pid)


@router.get("/status")
def status():
    return sandbox.docker_status()


class NewProject(BaseModel):
    name: str
    description: str = ""


@router.get("/projects")
def list_projects():
    return projects.list_all()


@router.post("/projects")
def create_project(req: NewProject):
    if not req.name.strip():
        raise HTTPException(400, "Give the project a name")
    return projects.create(req.name, req.description)


@router.get("/projects/{pid}")
def get_project(pid: str):
    meta = _project(pid)
    s = agent.session(pid)
    try:
        ports = sandbox.ports(pid)
    except Exception:
        ports = {}
    return {**meta, "running": s.running, "ports": ports, "shells": sandbox.list_background(pid)}


@router.patch("/projects/{pid}")
def update_project(pid: str, patch: dict):
    _project(pid)
    return projects.update(pid, patch)


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    _project(pid)
    agent.stop(pid)
    sandbox.stop(pid)
    projects.delete(pid)
    agent._sessions.pop(pid, None)
    return {"ok": True}


@router.get("/projects/{pid}/memory")
def project_memory(pid: str):
    """Memory options for this project's model on this computer."""
    from .. import readiness
    from ..workers.manager import ModelNotFound, manager

    meta = _project(pid)
    try:
        model = manager.resolve(meta.get("model"), "chat")
    except ModelNotFound as e:
        raise HTTPException(404, str(e))
    if model["engine"] != "llamacpp":
        raise HTTPException(400, "This project's model isn't a GGUF chat model")
    return {"model": model["id"], **readiness.memory_options(model)}


@router.get("/projects/{pid}/files")
def list_files(pid: str):
    _project(pid)
    return projects.tree(pid)


@router.get("/projects/{pid}/file", response_class=PlainTextResponse)
def read_file(pid: str, path: str):
    _project(pid)
    try:
        p = tools._resolve(pid, path)
        if p.stat().st_size > 2_000_000:
            raise HTTPException(413, "This file is too large to show here.")
        return tools._read_text(p)
    except tools.ToolError as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(404, "File not found")


@router.get("/projects/{pid}/zip")
def download(pid: str):
    _project(pid)
    return Response(projects.zip_bytes(pid), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{pid}.zip"'})


class Message(BaseModel):
    text: str


@router.post("/projects/{pid}/message")
async def send(pid: str, msg: Message):
    _project(pid)
    if not msg.text.strip():
        raise HTTPException(400, "Type a message first")
    try:
        agent.start(pid, msg.text.strip())
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


class Decision(BaseModel):
    event_id: str
    decision: str  # allow | deny | always


@router.post("/projects/{pid}/approve")
def approve(pid: str, d: Decision):
    _project(pid)
    if not agent.approve(pid, d.event_id, d.decision):
        raise HTTPException(409, "That request is no longer waiting for approval.")
    return {"ok": True}


@router.post("/projects/{pid}/stop")
def stop(pid: str):
    _project(pid)
    agent.stop(pid)
    return {"ok": True}


@router.post("/projects/{pid}/reset")
def reset(pid: str):
    _project(pid)
    s = agent.session(pid)
    if s.running:
        raise HTTPException(409, "Stop the agent before starting a new conversation.")
    s.reset()
    return {"ok": True}


@router.post("/projects/{pid}/sandbox/stop")
def stop_sandbox(pid: str):
    _project(pid)
    sandbox.stop(pid)
    return {"ok": True}


@router.get("/projects/{pid}/events")
async def events(pid: str):
    """A snapshot of the session, then live updates, as Server-Sent Events."""
    _project(pid)
    s = agent.session(pid)
    q: asyncio.Queue = asyncio.Queue()
    s.listeners.add(q)

    async def stream():
        try:
            yield f"data: {json.dumps(s.snapshot())}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            s.listeners.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
