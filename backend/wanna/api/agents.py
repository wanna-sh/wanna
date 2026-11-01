"""Agents API: agents, their inbox, files and live events (Server-Sent Events), and webhooks that wake them."""

from __future__ import annotations

import asyncio
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .. import agents
from ..code import projects, sandbox, tools
from .auth import require_key

router = APIRouter(prefix="/api/agents", dependencies=[Depends(require_key)])
# Webhooks carry the agent's own token in the link instead of an API key, so other services can call them.
hooks = APIRouter(prefix="/api/agents")

HOOK_LIMIT = 100_000  # bytes of a webhook body


def _agent(aid: str) -> agents.Agent:
    try:
        return agents.agent(aid)
    except agents.AgentError:
        raise HTTPException(404, "Agent not found")


def _patch(aid: str, patch: dict) -> dict:
    try:
        return agents.update(aid, patch)
    except agents.AgentError as e:
        raise HTTPException(400, str(e))
    except (TypeError, ValueError):
        raise HTTPException(400, "One of the settings has the wrong type.")


class NewAgent(BaseModel):
    name: str
    goals: str = ""
    model: str | None = None
    pace: str = "when_needed"
    start: bool = False


@router.get("")
def list_agents():
    return agents.list_all()


# Endpoints that turn agents on and off or reach into them are async: agents live on the server's event loop.

@router.post("")
async def create_agent(req: NewAgent):
    if not req.name.strip():
        raise HTTPException(400, "Give the agent a name")
    meta = agents.create(req.name, req.goals, req.model, req.pace)
    if req.start:
        agents.agent(meta["id"]).turn_on()
    return agents.public(meta)


@router.get("/{aid}")
def get_agent(aid: str):
    a = _agent(aid)
    meta = agents.get(aid)
    try:
        ports = sandbox.ports(a.pid)
    except Exception:
        ports = {}
    return {**agents.public(meta), "state": a.status(), "running": a.state != "off", "ports": ports}


@router.patch("/{aid}")
def update_agent(aid: str, patch: dict):
    _agent(aid)
    patch.pop("hook_token", None)
    return agents.public(_patch(aid, patch))


@router.delete("/{aid}")
async def delete_agent(aid: str):
    _agent(aid)
    await agents.delete(aid)
    return {"ok": True}


@router.post("/{aid}/on")
async def turn_on(aid: str):
    _agent(aid).turn_on()
    return {"ok": True}


@router.post("/{aid}/off")
async def turn_off(aid: str):
    _agent(aid).turn_off()
    return {"ok": True}


class Message(BaseModel):
    text: str


@router.post("/{aid}/message")
async def send(aid: str, msg: Message):
    a = _agent(aid)
    if not msg.text.strip():
        raise HTTPException(400, "Type a message first")
    a.deliver("you", msg.text)
    return {"ok": True, "on": a.state != "off"}


class Decision(BaseModel):
    event_id: str
    decision: str  # allow | deny | always


@router.post("/{aid}/approve")
async def approve(aid: str, d: Decision):
    fut = _agent(aid).approvals.get(d.event_id)
    if not fut or fut.done():
        raise HTTPException(409, "That request is no longer waiting for approval.")
    fut.set_result(d.decision if d.decision in ("allow", "deny", "always") else "deny")
    return {"ok": True}


@router.post("/{aid}/reset")
async def reset(aid: str):
    a = _agent(aid)
    if a.state != "off":
        raise HTTPException(409, "Turn the agent off before clearing its conversation.")
    a.reset()
    return {"ok": True}


@router.post("/{aid}/read")
async def mark_read(aid: str):
    _agent(aid).mark_read()
    return {"ok": True}


@router.post("/{aid}/hook/new")
def new_hook(aid: str):
    """A new webhook link; the old one stops working."""
    _agent(aid)
    meta = agents.get(aid)
    meta["hook_token"] = secrets.token_urlsafe(24)
    agents._save_meta(meta)
    return {"hook_token": meta["hook_token"]}


@router.get("/{aid}/hook")
def hook_token(aid: str):
    _agent(aid)
    return {"hook_token": agents.get(aid)["hook_token"]}


@router.post("/{aid}/sandbox/stop")
def stop_sandbox(aid: str):
    a = _agent(aid)
    if a.state != "off":
        raise HTTPException(409, "Turn the agent off first: its services run in the sandbox.")
    sandbox.stop(a.pid)
    return {"ok": True}


@router.get("/{aid}/memory")
def memory_options(aid: str):
    """Memory options for this agent's model on this computer."""
    from .. import readiness
    from ..workers.manager import ModelNotFound, manager

    _agent(aid)
    try:
        model = manager.resolve(agents.get(aid).get("model"), "chat")
    except ModelNotFound as e:
        raise HTTPException(404, str(e))
    if model["engine"] != "llamacpp":
        raise HTTPException(400, "This agent's model isn't a GGUF chat model")
    return {"model": model["id"], **readiness.memory_options(model)}


@router.get("/{aid}/files")
def list_files(aid: str):
    return projects.tree(_agent(aid).pid)


@router.get("/{aid}/file", response_class=PlainTextResponse)
def read_file(aid: str, path: str):
    a = _agent(aid)
    try:
        p = tools._resolve(a.pid, path)
        if p.stat().st_size > 2_000_000:
            raise HTTPException(413, "This file is too large to show here.")
        return tools._read_text(p)
    except tools.ToolError as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(404, "File not found")


@router.get("/{aid}/events")
async def events(aid: str):
    """A snapshot of the agent, then live updates, as Server-Sent Events."""
    a = _agent(aid)
    q: asyncio.Queue = asyncio.Queue()
    a.listeners.add(q)

    async def stream():
        try:
            yield f"data: {json.dumps(a.snapshot())}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            a.listeners.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@hooks.post("/{aid}/hook/{token}")
async def hook(aid: str, token: str, request: Request):
    """Wake the agent with whatever is posted: JSON or text. It arrives in its inbox, marked as a webhook."""
    meta = agents.get(aid) if len(aid) == 12 else None
    if meta is None or not secrets.compare_digest(token, meta.get("hook_token", "")):
        raise HTTPException(404, "Not found")
    body = await request.body()
    if len(body) > HOOK_LIMIT:
        raise HTTPException(413, f"Webhook bodies can be up to {HOOK_LIMIT // 1000} KB.")
    text = body.decode(errors="replace")
    try:
        text = json.dumps(json.loads(text), indent=1, ensure_ascii=False)
    except json.JSONDecodeError:
        pass
    if not text.strip():
        text = "(empty webhook)"
    a = agents.agent(aid)
    a.deliver("webhook", text, by=request.headers.get("user-agent", "")[:80])
    return {"ok": True, "on": a.state != "off"}
