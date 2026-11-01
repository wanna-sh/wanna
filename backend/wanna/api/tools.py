"""Custom tools under /api/tools: list, write, test, turn on or off, trust, and run them (see usertools.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import usertools
from .auth import require_key

router = APIRouter(prefix="/api/tools", dependencies=[Depends(require_key)])


class SaveReq(BaseModel):
    source: str = Field(max_length=200_000)
    old_name: str | None = None


class ConfigReq(BaseModel):
    enabled: bool | None = None
    trusted: bool | None = None


class RunReq(BaseModel):
    arguments: dict | str | None = None
    test: bool = False


def _fail(e: usertools.ToolError):
    return HTTPException(404 if "There's no tool" in str(e) else 400, str(e))


@router.get("")
def list_tools():
    """Every tool in the tools folder, with what the AI is told about it and any problem in its code."""
    return {"folder": str(usertools.TOOLS_DIR), "tools": usertools.list_tools(), "template": usertools.TEMPLATE}


@router.get("/schemas")
def tool_schemas():
    """The function schemas of the tools that are on, ready to send to a model."""
    return usertools.schemas()


@router.get("/{name}")
def get_tool(name: str):
    try:
        return usertools.get(name)
    except usertools.ToolError as e:
        raise _fail(e)


@router.put("/{name}")
def save_tool(name: str, req: SaveReq):
    try:
        return usertools.save(name, req.source, req.old_name)
    except usertools.ToolError as e:
        raise _fail(e)


@router.delete("/{name}")
def delete_tool(name: str):
    try:
        usertools.delete(name)
    except usertools.ToolError as e:
        raise _fail(e)
    return {"ok": True}


@router.post("/{name}/settings")
def configure_tool(name: str, req: ConfigReq):
    try:
        return usertools.configure(name, req.enabled, req.trusted)
    except usertools.ToolError as e:
        raise _fail(e)


@router.post("/{name}/run")
async def run_tool(name: str, req: RunReq):
    """Run a tool with these arguments. Failures come back as {"ok": false, "error"}, for the AI or the person."""
    return await run_in_threadpool(usertools.run, name, req.arguments, test=req.test)
