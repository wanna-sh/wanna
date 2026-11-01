"""Your own AI for a task, under /api/tasks: see tasks.py."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import tasks
from .auth import require_key

router = APIRouter(prefix="/api/tasks", dependencies=[Depends(require_key)])

MAX_FILE = 200 * 1024 * 1024


def _fail(e: tasks.TaskError):
    return HTTPException(404 if "no task with that id" in str(e) else 400, str(e))


async def _read(files: list[UploadFile], limit: int = 20_000) -> list[tuple[str, bytes]]:
    out = []
    for f in files[:limit]:
        data = await f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise HTTPException(413, f"{f.filename} is over 200 MB.")
        out.append((f.filename or "file", data))
    return out


@router.get("")
def list_tasks():
    from .. import db

    return {"tasks": tasks.list_tasks(), "search_model": any(m["task"] == "embed" for m in db.list_models())}


@router.post("")
async def create(name: str = Form(""), description: str = Form(""), files: list[UploadFile] = File(...)):
    """A new task from examples: a table (CSV, TSV, JSON or JSONL), or pictures, each named folder/picture.jpg so
    the folder is its answer."""
    try:
        return tasks.create(name, description, await _read(files))
    except tasks.TaskError as e:
        raise _fail(e)


@router.get("/{tid}")
def get(tid: str):
    try:
        return tasks.get(tid)
    except tasks.TaskError as e:
        raise _fail(e)


class Update(BaseModel):
    name: str | None = None
    description: str | None = None
    answer_column: str | None = None
    input_columns: list[str] | None = None
    threshold: float | None = None
    labels: list[str] | None = None
    no_answers: str | None = None  # "label" or "text": the examples have no answers yet
    in_chat: bool | None = None


@router.patch("/{tid}")
def update(tid: str, req: Update):
    try:
        return tasks.update(tid, **req.model_dump())
    except tasks.TaskError as e:
        raise _fail(e)


@router.delete("/{tid}")
def delete(tid: str):
    try:
        tasks.delete(tid)
    except tasks.TaskError as e:
        raise _fail(e)
    return {"ok": True}


@router.get("/{tid}/examples")
def examples(tid: str, offset: int = 0, limit: int = 50, show: str = "all"):
    """A page of examples, numbered, for checking answers: show is all, unanswered or drafted (answered by AI and not
    yet checked)."""
    try:
        rows = list(enumerate(tasks.examples(tid)))
    except tasks.TaskError as e:
        raise _fail(e)
    if show == "unanswered":
        rows = [(i, r) for i, r in rows if r.get("answer") in (None, "")]
    elif show == "drafted":
        rows = [(i, r) for i, r in rows if r.get("drafted")]
    return {"total": len(rows), "rows": [{"n": i, **r} for i, r in rows[offset:offset + min(limit, 500)]]}


class Answers(BaseModel):
    answers: dict[str, str | None]


@router.put("/{tid}/answers")
def answers(tid: str, req: Answers):
    try:
        return tasks.set_answers(tid, req.answers)
    except tasks.TaskError as e:
        raise _fail(e)


class Train(BaseModel):
    chat_model: str | None = None  # for tasks that write text: the chat model to train


@router.post("/{tid}/train")
async def train(tid: str, req: Train | None = None):  # async: training is scheduled on the server's event loop
    try:
        return tasks.start(tid, (req or Train()).chat_model)
    except tasks.TaskError as e:
        raise _fail(e)


class Draft(BaseModel):
    chat_model: str
    limit: int = 200
    careful: bool = True  # let the model reason before each answer: slower, more often right


@router.post("/{tid}/draft")
async def draft(tid: str, req: Draft):
    """Have a chat model draft answers for examples that have none, for checking (they're marked "drafted")."""
    try:
        return tasks.draft(tid, req.chat_model, max(1, min(2000, req.limit)), req.careful)
    except tasks.TaskError as e:
        raise _fail(e)


class Run(BaseModel):
    input: dict | str | None = None
    inputs: list[dict | str] | None = None


@router.post("/{tid}/run")
async def run(tid: str, req: Run):
    """Answer one input ("input") or several ("inputs"): for a table, {column: value}; for text, a string."""
    items = req.inputs if req.inputs is not None else [req.input]
    try:
        out = await tasks.run(tid, items)
    except tasks.TaskError as e:
        raise _fail(e)
    return out[0] if req.inputs is None else {"answers": out}


@router.post("/{tid}/run-picture")
async def run_picture(tid: str, file: UploadFile = File(...)):
    try:
        return (await tasks.run(tid, [{"data": (await _read([file]))[0][1]}]))[0]
    except tasks.TaskError as e:
        raise _fail(e)


@router.post("/{tid}/run-file")
async def run_file(tid: str, file: UploadFile = File(...)):
    """Answer every row of a table file: the same file back as CSV, with the answers added."""
    name, data = (await _read([file]))[0]
    try:
        out_name, out = await tasks.run_file(tid, name, data)
    except tasks.TaskError as e:
        raise _fail(e)
    return Response(out, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{out_name}"'})


@router.get("/{tid}/pictures/{name}")
def picture(tid: str, name: str):
    if not re.fullmatch(r"\d{5}\.(png|jpe?g|webp|bmp|gif)", name):
        raise HTTPException(404, "No such picture")
    try:
        path = tasks._folder(tid) / "pictures" / name
    except tasks.TaskError as e:
        raise _fail(e)
    if not path.exists():
        raise HTTPException(404, "No such picture")
    return FileResponse(path)
