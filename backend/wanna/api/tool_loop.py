"""Chat completions where wanna.sh runs custom tools itself: a request with "wanna_tools" (true, or a list of names).

The model gets those tools next to any the app sends. While it only calls wanna.sh's tools, they run here and the
model goes again, until it answers. If it calls one of the app's own tools, the response goes back to the app as
usual, with only the app's calls in it; what wanna.sh ran on the way is in "wanna_messages" (assistant and tool
messages, in order), for the app to put before that response when it continues the conversation.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from .. import usertools

MAX_ROUNDS = 8  # rounds of tool calls before the model must answer without wanna.sh's tools


def _bad(message: str) -> HTTPException:
    return HTTPException(400, detail={"error": {"message": message, "type": "invalid_request_error",
                                                "code": "invalid_request_error"}})


def tools_for(wanted) -> list[dict]:
    """The schemas for "wanna_tools": true for every tool that's on, or a list of names."""
    if wanted is True:
        return usertools.schemas()
    if not isinstance(wanted, list) or not all(isinstance(n, str) for n in wanted):
        raise _bad('wanna_tools must be true (every tool that is on) or a list of tool names.')
    schemas = usertools.schemas(wanted)
    missing = sorted(set(wanted) - {s["function"]["name"] for s in schemas})
    if missing:
        raise _bad(f"These wanna.sh tools don't exist, are turned off or have a problem: {', '.join(missing)}.")
    return schemas


async def _run_calls(calls: list[dict]) -> list[dict]:
    out = []
    for c in calls:
        fn = c.get("function") or {}
        r = await run_in_threadpool(usertools.run, fn.get("name", ""), fn.get("arguments") or "{}")
        content = r["result"] if r["ok"] else f"Error: {r['error']}"
        out.append({"role": "tool", "tool_call_id": c.get("id"), "content": content})
    return out


def _split(calls: list[dict], ours: set[str]) -> tuple[list[dict], list[dict]]:
    mine = [c for c in calls if (c.get("function") or {}).get("name") in ours]
    return mine, [c for c in calls if c not in mine]


async def run(url: str, headers: dict, body: dict, wanted) -> object:
    schemas = tools_for(wanted)
    ours = {s["function"]["name"] for s in schemas}
    app_tools = [t for t in (body.get("tools") or []) if (t.get("function") or {}).get("name") not in ours]
    messages = list(body.get("messages") or [])
    if body.get("stream"):
        return StreamingResponse(_stream(url, headers, body, messages, schemas, app_tools, ours),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    done: list[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), headers=headers) as client:
        for n in range(MAX_ROUNDS + 1):
            last = n == MAX_ROUNDS
            tools = app_tools + ([] if last else schemas)
            req = {**body, "messages": messages, **({"tools": tools} if tools else {})}
            if not tools:
                req.pop("tools", None)
                req.pop("tool_choice", None)
            r = await client.post(url, json=req)
            if r.status_code != 200:
                raise HTTPException(r.status_code, detail=_detail(r.text))
            resp = r.json()
            msg = resp["choices"][0]["message"]
            mine, theirs = _split(msg.get("tool_calls") or [], ours)
            if not mine:
                break
            step = [{"role": "assistant", "content": msg.get("content"), "tool_calls": mine}, *await _run_calls(mine)]
            done += step
            if theirs:
                msg["tool_calls"], msg["content"] = theirs, None
                break
            messages += step
    if done:
        resp["wanna_messages"] = done
    return resp


def _detail(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": {"message": text[:500], "type": "server_error", "code": "server_error"}}


async def _stream(url, headers, body, messages, schemas, app_tools, ours):
    """Pass the model's text through as it comes; collect tool calls, and at the end of a round either run
    wanna.sh's (and go again) or hand the app's back."""
    cid, created, model = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time()), body.get("model")
    done: list[dict] = []

    def chunk(delta: dict, finish: str | None = None, **extra) -> str:
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra}) + "\n\n"

    yield chunk({"role": "assistant", "content": ""})
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), headers=headers) as client:
        for n in range(MAX_ROUNDS + 1):
            tools = app_tools + ([] if n == MAX_ROUNDS else schemas)
            req = {**body, "messages": messages, "stream": True, **({"tools": tools} if tools else {})}
            if not tools:
                req.pop("tools", None)
                req.pop("tool_choice", None)
            text, calls, finish, usage = "", {}, None, None
            async with client.stream("POST", url, json=req) as r:
                if r.status_code != 200:
                    yield "data: " + json.dumps(_detail((await r.aread()).decode(errors="replace"))) + "\n\n"
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    piece = json.loads(line[6:])
                    if "error" in piece:
                        yield line + "\n\n"
                        return
                    usage = piece.get("usage") or usage
                    for choice in piece.get("choices") or []:
                        delta = choice.get("delta") or {}
                        finish = choice.get("finish_reason") or finish
                        for tc in delta.get("tool_calls") or []:
                            c = calls.setdefault(tc.get("index", 0), {"id": None, "type": "function",
                                                                    "function": {"name": "", "arguments": ""}})
                            c["id"] = tc.get("id") or c["id"]
                            f = tc.get("function") or {}
                            c["function"]["name"] += f.get("name") or ""
                            c["function"]["arguments"] += f.get("arguments") or ""
                        passed = {k: v for k, v in delta.items() if k in ("content", "reasoning_content") and v}
                        if passed:
                            text += passed.get("content", "")
                            yield chunk(passed)
            mine, theirs = _split([calls[i] for i in sorted(calls)], ours)
            if not mine:
                if theirs:
                    yield chunk({"tool_calls": [{"index": i, **c} for i, c in enumerate(theirs)]})
                extra = {"wanna_messages": done} if done else {}
                yield chunk({}, "tool_calls" if theirs else (finish or "stop"), **extra, **({"usage": usage} if usage else {}))
                break
            step = [{"role": "assistant", "content": text or None, "tool_calls": mine}, *await _run_calls(mine)]
            done += step
            if theirs:
                yield chunk({"tool_calls": [{"index": i, **c} for i, c in enumerate(theirs)]})
                yield chunk({}, "tool_calls", wanna_messages=done)
                break
            messages = messages + step
    yield "data: [DONE]\n\n"
