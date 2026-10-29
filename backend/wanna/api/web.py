"""Web search and page reading for chat. The same tools the Code agent uses (see code/search.py and code/tools.py),
without a project: local and private-network addresses are always refused."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..code import search, tools
from .auth import require_key

router = APIRouter(prefix="/api/web", dependencies=[Depends(require_key)])


class SearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    max_results: int = Field(default=6, ge=1, le=10)


class FetchReq(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/search")
async def web_search(req: SearchReq):
    try:
        results, provider = await run_in_threadpool(search.search, req.query, req.max_results)
    except search.SearchError as e:
        raise HTTPException(502, str(e))
    return {"provider": provider, "results": results}


@router.post("/fetch")
async def web_fetch(req: FetchReq):
    try:
        text = await run_in_threadpool(tools.web_fetch, None, req.url)
    except tools.ToolError as e:
        raise HTTPException(422, str(e))
    return {"url": req.url, "text": text}
