"""The agent's tools, modelled on Claude Code's: read/write/edit files, search, shell, todos and the web.

Every path is resolved inside the project folder; anything that escapes it is refused.
"""

from __future__ import annotations

import fnmatch
import html
import json
import re
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from . import sandbox
from .projects import IGNORED_DIRS, folder

READ_LIMIT = 2000  # lines per read, like Claude Code
LINE_CLIP = 2000  # characters per line
MAX_RESULTS = 200


class ToolError(Exception):
    """A problem the model should see and can fix (bad path, edit didn't match, ...)."""


# --- schemas the model sees -----------------------------------------------------------------------

def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


SCHEMAS = [
    _fn("read_file", "Read a text file. Returns numbered lines. Read a file before editing it. For long files, use "
        "offset and limit to read a section.",
        {"path": {"type": "string", "description": "Path relative to the project root."},
         "offset": {"type": "integer", "description": "Line number to start at (1-based)."},
         "limit": {"type": "integer", "description": f"How many lines to read (default {READ_LIMIT})."}},
        ["path"]),
    _fn("write_file", "Create a file or replace its whole contents. Prefer edit_file for changes to existing files.",
        {"path": {"type": "string"}, "content": {"type": "string", "description": "The full file contents."}},
        ["path", "content"]),
    _fn("edit_file", "Replace exact text in a file. old_string must match the file exactly, including indentation, "
        "and appear once unless replace_all is true. Read the file first.",
        {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean", "description": "Replace every occurrence."}},
        ["path", "old_string", "new_string"]),
    _fn("multi_edit", "Make several exact-text replacements in one file, applied in order. All or nothing.",
        {"path": {"type": "string"},
         "edits": {"type": "array", "items": {"type": "object", "properties": {
             "old_string": {"type": "string"}, "new_string": {"type": "string"},
             "replace_all": {"type": "boolean"}}, "required": ["old_string", "new_string"]}}},
        ["path", "edits"]),
    _fn("list_files", "List files and folders as a tree. Skips dependency folders like node_modules and .git.",
        {"path": {"type": "string", "description": "Folder to list (default: project root)."},
         "depth": {"type": "integer", "description": "How many levels deep (default 3)."}},
        []),
    _fn("glob", "Find files by name pattern, e.g. '**/*.py' or 'src/**/*.tsx'. Newest first.",
        {"pattern": {"type": "string"}, "path": {"type": "string", "description": "Folder to search in."}},
        ["pattern"]),
    _fn("grep", "Search file contents with a regular expression.",
        {"pattern": {"type": "string", "description": "Regular expression."},
         "path": {"type": "string", "description": "File or folder to search (default: project root)."},
         "glob": {"type": "string", "description": "Only search files matching this pattern, e.g. '*.js'."},
         "ignore_case": {"type": "boolean"},
         "output_mode": {"type": "string", "enum": ["content", "files", "count"],
                         "description": "content: matching lines (default); files: just file names; count: matches per file."},
         "context": {"type": "integer", "description": "Lines of context around each match (content mode)."}},
        ["pattern"]),
    _fn("bash", "Run a shell command in the project's sandbox (Linux, Node 24, Python 3, git). The working "
        "directory is the project root. Use background for servers and long-running jobs.",
        {"command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Seconds before the command is stopped (default 120, max 600)."},
         "background": {"type": "boolean", "description": "Start it and return immediately with a shell_id."},
         "description": {"type": "string", "description": "A few words on what the command does, shown to the user."}},
        ["command"]),
    _fn("bash_output", "Read new output from a background command.",
        {"shell_id": {"type": "string"}}, ["shell_id"]),
    _fn("kill_shell", "Stop a background command.", {"shell_id": {"type": "string"}}, ["shell_id"]),
    _fn("todo_write", "Create or update your task list. Use it for any work with 3 or more steps. Send the whole "
        "list each time. Keep exactly one item in_progress while working.",
        {"todos": {"type": "array", "items": {"type": "object", "properties": {
            "content": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
            "required": ["content", "status"]}}},
        ["todos"]),
    _fn("web_fetch", "Fetch a web page and return its text, e.g. documentation or an API reference.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("web_search", "Search the web. Returns titles, links and snippets.",
        {"query": {"type": "string"}, "max_results": {"type": "integer", "description": "Default 8."}},
        ["query"]),
]

# Which tools change things (for approval modes).
COMMAND_TOOLS = {"bash", "kill_shell"}
EDIT_TOOLS = {"write_file", "edit_file", "multi_edit"}


# --- helpers ------------------------------------------------------------------------------------------

def _resolve(pid: str, path: str | None) -> Path:
    root = folder(pid).resolve()
    rel = (path or ".").strip().removeprefix("/workspace").lstrip("/") or "."
    p = (root / rel).resolve()
    if p != root and not p.is_relative_to(root):
        raise ToolError(f"{path} is outside the project folder.")
    return p


def _rel(pid: str, p: Path) -> str:
    return p.relative_to(folder(pid).resolve()).as_posix() or "."


def _read_text(p: Path) -> str:
    if not p.exists():
        raise ToolError(f"{p.name} doesn't exist.")
    if p.is_dir():
        raise ToolError(f"{p.name} is a folder. Use list_files.")
    data = p.read_bytes()
    if b"\x00" in data[:8000]:
        raise ToolError(f"{p.name} is a binary file.")
    return data.decode("utf-8", errors="replace")


def _walk(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            yield p


# --- file tools ------------------------------------------------------------------------------------------

def read_file(pid, path, offset=None, limit=None):
    p = _resolve(pid, path)
    lines = _read_text(p).splitlines()
    start = max(1, int(offset or 1))
    count = max(1, min(int(limit or READ_LIMIT), READ_LIMIT))
    chunk = lines[start - 1:start - 1 + count]
    body = "\n".join(f"{i:>6}\t{line[:LINE_CLIP]}" for i, line in enumerate(chunk, start))
    more = len(lines) - (start - 1 + len(chunk))
    if not lines:
        return "(empty file)"
    return body + (f"\n\n[{more} more lines. Read again with offset={start + len(chunk)}.]" if more > 0 else "")


def write_file(pid, path, content):
    p = _resolve(pid, path)
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"{'Updated' if existed else 'Created'} {_rel(pid, p)} ({len(content.splitlines())} lines)."


def _apply_edit(text, old, new, replace_all, path):
    if old == new:
        raise ToolError("old_string and new_string are the same.")
    n = text.count(old)
    if n == 0:
        raise ToolError(f"old_string wasn't found in {path}. Read the file and copy the text exactly.")
    if n > 1 and not replace_all:
        raise ToolError(f"old_string appears {n} times in {path}. Add more surrounding text to make it unique, "
                        "or set replace_all.")
    return text.replace(old, new) if replace_all else text.replace(old, new, 1), n if replace_all else 1


def edit_file(pid, path, old_string, new_string, replace_all=False):
    p = _resolve(pid, path)
    text, n = _apply_edit(_read_text(p), old_string, new_string, replace_all, path)
    p.write_text(text)
    return f"Edited {_rel(pid, p)} ({n} replacement{'s' if n != 1 else ''})."


def multi_edit(pid, path, edits):
    p = _resolve(pid, path)
    text = _read_text(p)
    total = 0
    for i, e in enumerate(edits, 1):
        try:
            text, n = _apply_edit(text, e["old_string"], e["new_string"], e.get("replace_all", False), path)
        except ToolError as err:
            raise ToolError(f"Edit {i}: {err} No changes were made.")
        total += n
    p.write_text(text)
    return f"Edited {_rel(pid, p)} ({len(edits)} edits, {total} replacements)."


def list_files(pid, path=None, depth=3):
    root = _resolve(pid, path)
    if not root.is_dir():
        raise ToolError(f"{path} is not a folder.")
    depth = max(1, min(int(depth or 3), 8))
    lines, count = [], 0

    def walk(d: Path, level: int, indent: str):
        nonlocal count
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except OSError:
            return
        for e in entries:
            if count >= 500:
                return
            if e.is_dir():
                if e.name in IGNORED_DIRS:
                    lines.append(f"{indent}{e.name}/ (skipped)")
                    continue
                lines.append(f"{indent}{e.name}/")
                count += 1
                if level < depth:
                    walk(e, level + 1, indent + "  ")
            else:
                lines.append(f"{indent}{e.name}")
                count += 1

    walk(root, 1, "")
    return "\n".join(lines) if lines else "(empty folder)"


def glob(pid, pattern, path=None):
    root = _resolve(pid, path)
    pat = pattern.lstrip("./")
    hits = [p for p in _walk(root) if fnmatch.fnmatch(p.relative_to(root).as_posix(), pat)
            or ("/" not in pat and fnmatch.fnmatch(p.name, pat))]
    hits.sort(key=lambda p: -p.stat().st_mtime)
    if not hits:
        return "No files matched."
    shown = "\n".join(_rel(pid, p) for p in hits[:MAX_RESULTS])
    return shown + (f"\n[{len(hits) - MAX_RESULTS} more not shown]" if len(hits) > MAX_RESULTS else "")


def grep(pid, pattern, path=None, glob=None, ignore_case=False, output_mode="content", context=0):
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ToolError(f"Invalid regular expression: {e}")
    root = _resolve(pid, path)
    ctx = max(0, min(int(context or 0), 10))
    out, files, total = [], 0, 0
    for p in _walk(root):
        if glob and not fnmatch.fnmatch(p.name, glob) and not fnmatch.fnmatch(_rel(pid, p), glob):
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8000]:
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        matches = [i for i, line in enumerate(lines) if rx.search(line)]
        if not matches:
            continue
        files += 1
        total += len(matches)
        rel = _rel(pid, p)
        if output_mode == "files":
            out.append(rel)
        elif output_mode == "count":
            out.append(f"{rel}: {len(matches)}")
        else:
            shown = set()
            for i in matches:
                for j in range(max(0, i - ctx), min(len(lines), i + ctx + 1)):
                    if j not in shown:
                        shown.add(j)
                        sep = ":" if j == i else "-"
                        out.append(f"{rel}{sep}{j + 1}{sep}{lines[j][:LINE_CLIP]}")
        if len(out) >= MAX_RESULTS:
            out.append(f"[stopped after {MAX_RESULTS} results]")
            break
    if not out:
        return "No matches."
    return "\n".join(out) + f"\n\n({total} matches in {files} files)"


# --- shell ---------------------------------------------------------------------------------------------------

def bash(pid, command, timeout=120, background=False, description=None, cancel: threading.Event | None = None):
    if background:
        return sandbox.start_background(pid, command)
    return sandbox.run(pid, command, timeout, cancel)


def bash_output(pid, shell_id):
    return sandbox.background_output(shell_id)


def kill_shell(pid, shell_id):
    return sandbox.kill_background(shell_id)


# --- web --------------------------------------------------------------------------------------------------------

class _Text(HTMLParser):
    """HTML to readable text: drops scripts/styles/nav, keeps headings, paragraphs, lists and links."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.out.append("#" * int(tag[1]) + " ")
            if tag == "li":
                self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def web_fetch(pid, url):
    if not re.match(r"^https?://", url):
        raise ToolError("Only http and https links can be fetched.")
    try:
        r = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0 (wanna.sh code agent)"})
    except httpx.HTTPError as e:
        raise ToolError(f"Couldn't fetch {url}: {e}")
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 400:
        raise ToolError(f"{url} returned HTTP {r.status_code}.")
    if "html" in ctype:
        parser = _Text()
        parser.feed(r.text)
        body = parser.text()
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        body = r.text
    else:
        raise ToolError(f"{url} isn't a text page ({ctype or 'unknown type'}).")
    clipped = body[:20_000]
    return f"URL: {r.url}\n\n{clipped}" + ("\n\n[page cut off at 20,000 characters]" if len(body) > 20_000 else "")


def web_search(pid, query, max_results=8):
    """Keyless search via DuckDuckGo's HTML results page."""
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=20,
                       headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ToolError(f"Search failed: {e}")
    if r.status_code == 202 or "anomaly" in r.text[:20000].lower():
        # DuckDuckGo shows a bot check after many searches from one address.
        raise ToolError("Web search is temporarily unavailable: DuckDuckGo is asking for a human check after too many "
                        "searches. Try again in a while, or use web_fetch on a documentation page you know.")
    results = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         r.text, re.S):
        href, title, snippet = m.groups()
        q = parse_qs(urlparse(html.unescape(href)).query)
        link = unquote(q["uddg"][0]) if "uddg" in q else html.unescape(href)
        if "duckduckgo.com/y.js" in link:
            continue  # ads
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
        results.append(f"{clean(title)}\n{link}\n{clean(snippet)}")
        if len(results) >= max(1, min(int(max_results or 8), 15)):
            break
    if not results:
        raise ToolError("No results. The search service may be busy; try again or rephrase.")
    return "\n\n".join(results)


# --- dispatch ----------------------------------------------------------------------------------------------------

FUNCS = {
    "read_file": read_file, "write_file": write_file, "edit_file": edit_file, "multi_edit": multi_edit,
    "list_files": list_files, "glob": glob, "grep": grep, "bash": bash, "bash_output": bash_output,
    "kill_shell": kill_shell, "web_fetch": web_fetch, "web_search": web_search,
}


def call(pid: str, name: str, args: dict, cancel: threading.Event | None = None) -> str:
    """Run a tool and return text for the model. Problems come back as text the model can act on."""
    fn = FUNCS.get(name)
    if fn is None:
        return f"Error: there's no tool called {name}."
    try:
        kwargs = dict(args)
        if name == "bash":
            kwargs["cancel"] = cancel
        result = fn(pid, **kwargs)
    except ToolError as e:
        return f"Error: {e}"
    except sandbox.SandboxError as e:
        return f"Error: {e}"
    except TypeError as e:
        return f"Error: wrong arguments for {name}: {e}"
    except Exception as e:  # never let a tool crash the agent
        return f"Error: {type(e).__name__}: {e}"
    if isinstance(result, dict):
        if name == "bash" and "exit_code" in result:
            note = f"\n[{result['note']}]" if result.get("note") else ""
            code = "timed out" if result["exit_code"] is None else f"exit code {result['exit_code']}"
            return f"{result['output'] or '(no output)'}\n[{code}]{note}"
        return json.dumps(result)
    return result
