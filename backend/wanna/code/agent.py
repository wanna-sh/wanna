"""The coding agent: a model works in a project by calling tools, step by step, until the task is done.

Each project has one session: the model's message history, plus a list of events the page renders
(your messages, the agent's text, tool calls with their results and diffs, approvals, the todo list).
The page gets a snapshot and then live updates over Server-Sent Events, so it can reconnect mid-turn.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import time
import uuid

import httpx

from ..workers.manager import LoadError, ModelNotFound, manager
from . import projects, sandbox, tools

log = logging.getLogger("wanna.code.agent")

MAX_STEPS = 50  # tool-using steps per request before the agent must stop and report
TOOL_RESULT_EVENT_LIMIT = 20_000  # characters of a tool result kept for display
SCHEMA_TOKENS = 2500  # rough size of the tool definitions in the prompt

SYSTEM_PROMPT = """You are wanna.sh Code, a careful software engineer working in the user's project.

Environment
- The project folder is /workspace, a Linux sandbox with Node 24, npm, Python 3.11, pip and git. Tool paths are relative to the project root.
- Shell commands run with the bash tool. The sandbox can reach the internet (package installs, git clone).
- To show the user a web app, start its server with bash background=true, listening on 0.0.0.0 and port 3000, 5173, 8000 or 8080. The user opens it from the Preview links in the app.

How to work
- Understand before changing: use list_files, glob, grep and read_file. Read a file before editing it.
- For work with 3 or more steps, plan it with todo_write and keep the list current: mark one item in_progress at a time and complete items as soon as they are done.
- Prefer edit_file for small changes and write_file for new files. Keep changes focused on what was asked; follow the project's existing style.
- After changing code, check it works: run it, its tests, or a build. If something fails, read the error and fix it.
- Don't run destructive commands (deleting files or history, force pushes) unless the user asked for that.
- If the request is unclear or a decision is the user's to make, ask a short question instead of guessing.

Communicating
- Be concise. Don't narrate every tool call; the user can see them.
- When you finish, give a short summary: what you built or changed, and how to run or open it."""


def _id() -> str:
    return uuid.uuid4().hex[:12]


class Session:
    def __init__(self, pid: str):
        self.pid = pid
        data = projects.load_session(pid)
        self.messages: list[dict] = data.get("messages", [])
        self.events: list[dict] = data.get("events", [])
        self.todos: list[dict] = data.get("todos", [])
        self.running = False
        self.cancel = None  # threading.Event while a turn runs
        self.approvals: dict[str, asyncio.Future] = {}
        self.listeners: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        # Anything left mid-flight by a restart can't continue.
        for e in self.events:
            if e.get("status") in ("running", "awaiting_approval"):
                e["status"] = "stopped"

    # --- events ------------------------------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {"type": "snapshot", "events": self.events, "todos": self.todos, "running": self.running}

    def _broadcast(self, msg: dict) -> None:
        for q in list(self.listeners):
            q.put_nowait(msg)

    def emit(self, event: dict) -> dict:
        event.setdefault("id", _id())
        event.setdefault("time", time.time())
        self.events.append(event)
        self._broadcast({"type": "upsert", "event": event})
        return event

    def touch(self, event: dict) -> None:
        self._broadcast({"type": "upsert", "event": event})

    def set_running(self, value: bool) -> None:
        self.running = value
        self._broadcast({"type": "status", "running": value})

    def save(self) -> None:
        projects.save_session(self.pid, {"messages": self.messages, "events": self.events, "todos": self.todos})

    def reset(self) -> None:
        self.messages, self.events, self.todos = [], [], []
        self.save()
        self._broadcast(self.snapshot())

    # --- a turn ----------------------------------------------------------------------------------------------

    async def run(self, text: str) -> None:
        import threading

        self.cancel = threading.Event()
        self.set_running(True)
        self.emit({"type": "user", "text": text})
        self.messages.append({"role": "user", "content": text})
        try:
            await self._loop()
        except asyncio.CancelledError:
            self.emit({"type": "notice", "text": "Stopped."})
        except (ModelNotFound, LoadError) as e:
            self.emit({"type": "error", "text": str(e)})
        except Exception as e:
            log.exception("code agent failed")
            self.emit({"type": "error", "text": f"Something went wrong: {type(e).__name__}: {e}"})
        finally:
            for f in self.approvals.values():
                if not f.done():
                    f.set_result("deny")
            self.approvals.clear()
            self.set_running(False)
            self.save()

    async def _loop(self) -> None:
        meta = projects.get(self.pid) or {}
        context = int(meta.get("context") or 16384)
        model = manager.resolve(meta.get("model"), "chat")
        worker = manager.get(model["id"])
        if worker and worker.context != context:
            self.emit({"type": "notice", "text": f"Restarting {model['id']} with more memory for coding "
                                                  f"({context // 1024}K)."})
        if not worker or worker.context != context:
            worker = await asyncio.to_thread(manager.load, model["id"], None, context)
        worker = await manager.ensure_ready(model)
        if model["engine"] != "llamacpp":
            raise LoadError("Code needs a GGUF chat model (the kind that runs on llama.cpp). Pick one in the model menu.")

        for step in range(MAX_STEPS):
            if self.cancel.is_set():
                self.emit({"type": "notice", "text": "Stopped."})
                return
            reply = await self._call_model(worker.url, model["id"], context)
            content, calls, thinking = reply["content"], reply["tool_calls"], reply["thinking"]
            assistant = {"role": "assistant", "content": content or None}
            if calls:
                assistant["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ]
            self.messages.append(assistant)
            self.save()
            if not calls:
                if not content.strip() and not thinking:
                    self.emit({"type": "notice", "text": "The model stopped without a reply."})
                return
            for c in calls:
                if self.cancel.is_set():
                    break
                result = await self._run_tool(c, meta)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
                self.save()
                meta = projects.get(self.pid) or meta  # "always allow" may have changed
        self.emit({"type": "notice", "text": f"Paused after {MAX_STEPS} steps. Say \"continue\" to keep going."})

    async def _call_model(self, url: str, model_id: str, context: int) -> dict:
        """One streamed request. Text appears live; tool calls are collected from their deltas."""
        payload = {
            "model": model_id,
            "messages": [{"role": "system", "content": self._system()}] + self._fit(context),
            "tools": tools.SCHEMAS,
            "stream": True,
            "temperature": 0.3,
        }
        content, thinking = "", ""
        calls: dict[int, dict] = {}
        event = None
        last_push = 0.0
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10)) as client:
            async with client.stream("POST", f"{url}/v1/chat/completions", json=payload) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")
                    raise RuntimeError(_model_error(body))
                async for line in r.aiter_lines():
                    if self.cancel.is_set():
                        break
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError(_model_error(json.dumps(chunk)))
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        thinking += delta["reasoning_content"]
                    if delta.get("content"):
                        content += delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
                    if (content or thinking) and event is None:
                        event = self.emit({"type": "assistant", "text": "", "thinking": ""})
                    if event and time.time() - last_push > 0.08:
                        event["text"], event["thinking"] = content, thinking
                        self.touch(event)
                        last_push = time.time()
        if event:
            event["text"], event["thinking"] = content, thinking
            self.touch(event)
        out = []
        for slot in calls.values():
            if slot["name"]:
                out.append({"id": slot["id"] or f"call_{_id()}", "name": slot["name"], "arguments": slot["arguments"] or "{}"})
        return {"content": content, "thinking": thinking, "tool_calls": out, "event": event}

    async def _run_tool(self, call: dict, meta: dict) -> str:
        name = call["name"]
        try:
            args = json.loads(call["arguments"]) if call["arguments"].strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except (json.JSONDecodeError, ValueError) as e:
            self.emit({"type": "tool", "name": name, "args": {}, "status": "error",
                       "result": f"The model sent invalid arguments: {e}"})
            return f"Error: your arguments for {name} weren't valid JSON ({e}). Try again."

        event = self.emit({"type": "tool", "call_id": call["id"], "name": name, "args": args, "status": "running"})

        if name == "todo_write":
            todos = [t for t in args.get("todos", []) if isinstance(t, dict) and t.get("content")]
            self.todos = [{"content": str(t["content"]), "status": t.get("status", "pending")} for t in todos]
            self._broadcast({"type": "todos", "todos": self.todos})
            event["status"], event["result"] = "done", f"{len(self.todos)} tasks"
            self.touch(event)
            done = sum(t["status"] == "completed" for t in self.todos)
            return f"Todo list updated ({done}/{len(self.todos)} completed)."

        if self._needs_approval(name, args, meta):
            event["status"] = "awaiting_approval"
            self.touch(event)
            fut = asyncio.get_running_loop().create_future()
            self.approvals[event["id"]] = fut
            decision = await fut
            self.approvals.pop(event["id"], None)
            if decision == "deny":
                event["status"], event["result"] = "denied", "You declined this."
                self.touch(event)
                return "The user declined this action. Ask them how they'd like to proceed, or try a different approach."
            if decision == "always" and name == "bash":
                m = projects.get(self.pid) or meta
                if args.get("command") not in m["always_allow"]:
                    m["always_allow"].append(args.get("command"))
                    projects.save(m)
            event["status"] = "running"
            self.touch(event)

        before = self._snapshot_file(name, args)
        result = await asyncio.to_thread(tools.call, self.pid, name, args, self.cancel)
        event["status"] = "error" if result.startswith("Error:") else "done"
        event["result"] = result[:TOOL_RESULT_EVENT_LIMIT]
        if before is not None and event["status"] == "done":
            event["diff"] = self._diff(args.get("path", ""), before)
        if name == "bash" and args.get("background"):
            event["ports"] = sandbox.ports(self.pid)
        self.touch(event)
        return result

    # --- helpers ------------------------------------------------------------------------------------------

    def _needs_approval(self, name: str, args: dict, meta: dict) -> bool:
        mode = meta.get("approval", "ask_commands")
        if mode == "auto":
            return False
        if name in tools.COMMAND_TOOLS:
            return not (name == "bash" and args.get("command") in meta.get("always_allow", []))
        return mode == "ask_all" and name in tools.EDIT_TOOLS

    def _snapshot_file(self, name: str, args: dict) -> str | None:
        """File contents before an edit, so the page can show a diff."""
        if name not in tools.EDIT_TOOLS or not args.get("path"):
            return None
        try:
            p = tools._resolve(self.pid, args["path"])
            return p.read_text(errors="replace") if p.is_file() else ""
        except Exception:
            return None

    def _diff(self, path: str, before: str) -> str:
        try:
            after = tools._resolve(self.pid, path).read_text(errors="replace")
        except Exception:
            return ""
        lines = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{path}", f"b/{path}", lineterm="", n=2)
        diff = "\n".join(lines)
        return diff[:15_000] + ("\n[diff cut off]" if len(diff) > 15_000 else "")

    def _system(self) -> str:
        meta = projects.get(self.pid) or {}
        extra = f"\n\nProject: {meta.get('name')}"
        if meta.get("description"):
            extra += f"\nWhat it is: {meta['description']}"
        files = projects.tree(self.pid, limit=60)
        if files:
            extra += "\nFiles at the start of this request (first 60):\n" + "\n".join(f"- {f['path']}" for f in files)
        else:
            extra += "\nThe project folder is empty."
        return SYSTEM_PROMPT + extra

    def _fit(self, context: int) -> list[dict]:
        """Keep the conversation within the model's memory: shrink old tool output first, then drop old turns."""
        budget = int((context - SCHEMA_TOKENS - 2000) * 0.8 * 3.5)  # characters, leaving room for the reply
        msgs = [dict(m) for m in self.messages]
        size = lambda: sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls", ""))) for m in msgs)
        for m in msgs[:-6]:
            if size() <= budget:
                break
            if m["role"] == "tool" and len(m.get("content") or "") > 300:
                m["content"] = m["content"][:300] + "\n[older output removed to save memory]"
        while size() > budget and len(msgs) > 4:
            # Drop from the oldest, never leaving a tool result without the call that made it.
            msgs.pop(0)
            while msgs and msgs[0]["role"] == "tool":
                msgs.pop(0)
        return msgs


def _model_error(body: str) -> str:
    try:
        msg = json.loads(body).get("error", {}).get("message", body)
    except (json.JSONDecodeError, AttributeError):
        msg = body
    if "context" in msg.lower() and ("exceed" in msg.lower() or "too long" in msg.lower()):
        return "The conversation is too long for this model's memory. Start a new conversation, or raise Memory in this project's settings."
    return f"The model returned an error: {msg[:300]}"


_sessions: dict[str, Session] = {}


def session(pid: str) -> Session:
    s = _sessions.get(pid)
    if s is None:
        s = _sessions[pid] = Session(pid)
    return s


def start(pid: str, text: str) -> None:
    s = session(pid)
    if s.running:
        raise RuntimeError("The agent is already working on something. Wait for it to finish or press Stop.")
    s.task = asyncio.create_task(s.run(text))


def stop(pid: str) -> None:
    s = session(pid)
    if s.cancel:
        s.cancel.set()
    for f in s.approvals.values():
        if not f.done():
            f.set_result("deny")


def approve(pid: str, event_id: str, decision: str) -> bool:
    fut = session(pid).approvals.get(event_id)
    if not fut or fut.done():
        return False
    fut.set_result(decision if decision in ("allow", "deny", "always") else "deny")
    return True
