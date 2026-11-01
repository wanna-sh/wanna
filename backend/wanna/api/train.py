"""Training your own picture styles (LoRAs) under /api/training: see training.py."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import training
from .auth import require_key

router = APIRouter(prefix="/api/training", dependencies=[Depends(require_key)])

MAX_PICTURE = 30 * 1024 * 1024


def _fail(e: training.TrainError):
    return HTTPException(404 if "no training run" in str(e) else 400, str(e))


@router.get("")
def overview():
    """Whether this computer can train, the picture models it can train, and every training run."""
    return {"ready": training.ready(), "models": training.models(), "runs": training.list_runs()}


@router.post("")
async def start(model: str = Form(...), preset: str = Form(...), trigger: str = Form(...), what: str = Form(""),
                name: str = Form(""), steps: int | None = Form(None), files: list[UploadFile] = File(...)):
    """Start training: a picture model, "subject" or "style", the trigger word, and 3 to 50 pictures."""
    pictures = []
    for f in files[:training.MAX_PICTURES + 1]:
        data = await f.read(MAX_PICTURE + 1)
        if len(data) > MAX_PICTURE:
            raise HTTPException(413, f"{f.filename} is over 30 MB.")
        pictures.append((f.filename or "picture.png", data))
    try:
        return training.create(model, preset, name, trigger, what, pictures, steps)
    except training.TrainError as e:
        raise _fail(e)


@router.get("/{rid}")
def get_run(rid: str):
    try:
        return training.get(rid)
    except training.TrainError as e:
        raise _fail(e)


class Rename(BaseModel):
    name: str


@router.patch("/{rid}")
def rename(rid: str, req: Rename):
    try:
        return training.rename(rid, req.name)
    except training.TrainError as e:
        raise _fail(e)


@router.post("/{rid}/stop")
def stop(rid: str):
    try:
        return training.stop(rid)
    except training.TrainError as e:
        raise _fail(e)


@router.post("/{rid}/restart")
def restart(rid: str):
    try:
        return training.restart(rid)
    except training.TrainError as e:
        raise _fail(e)


@router.delete("/{rid}")
def delete(rid: str):
    try:
        training.delete(rid)
    except training.TrainError as e:
        raise _fail(e)
    return {"ok": True}


@router.get("/{rid}/samples/{name}")
def sample(rid: str, name: str):
    """A sample picture made with the trained style."""
    if not re.fullmatch(r"\d{1,2}\.png", name):
        raise HTTPException(404, "No such sample")
    try:
        path = training._folder(rid) / "samples" / name
    except training.TrainError as e:
        raise _fail(e)
    if not path.exists():
        raise HTTPException(404, "No such sample")
    return FileResponse(path)
