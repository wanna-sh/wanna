"""The agent's tools, modelled on Claude Code's: read/write/edit files, search, shell, todos and the web.

Every path is resolved inside the project folder; anything that escapes it is refused.
"""

from __future__ import annotations

import fnmatch
import io
import ipaddress
import json
import re
import socket
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

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
    _fn("write_file", "Create a file or replace its whole contents. Prefer edit_file for changes to existing files. "
        "For long files (over about 150 lines), write the first part, then add the rest with append set to true.",
        {"path": {"type": "string"}, "content": {"type": "string", "description": "The file contents (or the part to add)."},
         "append": {"type": "boolean", "description": "Add content to the end of the file instead of replacing it."}},
        ["path", "content"]),
    _fn("edit_file", "Replace exact text in a file. old_string must match the file exactly, including indentation, "
        "and appear once unless replace_all is true. Read the file first. Leave out the line numbers read_file shows.",
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
    _fn("web_fetch", "Fetch a web page or PDF and return its text, e.g. documentation or an API reference. "
        "To check the project's own app, fetch http://localhost:<port> for a server running in the sandbox.",
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


# A line ends at \n, with any \r before it. Windows line endings are \r\n, and earlier versions of these tools added
# one more \r every time they saved a file on Windows, so lines can end in several.
_EOL = re.compile(r"\r*\n")


def _lines(text: str) -> list[str]:
    """The lines the model sees. Only \\n ends a line: str.splitlines also splits at a lone \\r, form feeds and
    Unicode separators, which shows blank lines that aren't there and puts line numbers out of step with the file."""
    lines = _EOL.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines


def _line_ending(text: str) -> str:
    """\\r\\n if most of the file's lines end that way, otherwise \\n."""
    crlf = len(re.findall(r"\r+\n", text))
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _write_text(p: Path, text: str, append: bool = False) -> None:
    # newline="" writes the text exactly as given. Without it Python turns every \n into \r\n on Windows, so files
    # made on Windows didn't match what the model read, and each edit added another \r to every line.
    with open(p, "a" if append else "w", encoding="utf-8", newline="") as f:
        f.write(text)


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
    lines = _lines(_read_text(p))
    start = max(1, int(offset or 1))
    count = max(1, min(int(limit or READ_LIMIT), READ_LIMIT))
    chunk = lines[start - 1:start - 1 + count]
    body = "\n".join(f"{i:>6}\t{line[:LINE_CLIP]}" for i, line in enumerate(chunk, start))
    more = len(lines) - (start - 1 + len(chunk))
    if not lines:
        return "(empty file)"
    return body + (f"\n\n[{more} more lines. Read again with offset={start + len(chunk)}.]" if more > 0 else "")


def write_file(pid, path, content, append=False):
    p = _resolve(pid, path)
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    if append and existed:
        if _line_ending(_read_text(p)) == "\r\n":  # keep a Windows file's line endings the same throughout
            content = _EOL.sub("\r\n", content)
        _write_text(p, content, append=True)
        total = len(_lines(_read_text(p)))
        return f"Added {len(_lines(content))} lines to {_rel(pid, p)} (now {total} lines)."
    _write_text(p, content)
    return f"{'Updated' if existed else 'Created'} {_rel(pid, p)} ({len(_lines(content))} lines)."


def _edit(p: Path, path: str, edits: list[tuple[str, str, bool]], numbered: bool = False) -> list[int]:
    """Apply exact-text edits to a file, all or nothing, and return how many replacements each made. With numbered,
    an error says which edit failed.

    The model reads lines without their \\r (see _lines), so edits are matched with every line ending as \\n, and the
    file is saved with the line ending most of it had. A Windows file stays \\r\\n, and the extra \\r that earlier
    versions added are dropped.
    """
    raw = _read_text(p)
    text = _EOL.sub("\n", raw)
    counts = []
    for i, (old, new, replace_all) in enumerate(edits, 1):
        try:
            text, n = _apply_edit(text, _EOL.sub("\n", old), _EOL.sub("\n", new), replace_all, path)
        except ToolError as err:
            if numbered:
                raise ToolError(f"Edit {i}: {err} No changes were made.")
            raise
        counts.append(n)
    eol = _line_ending(raw)
    _write_text(p, text.replace("\n", eol) if eol != "\n" else text)
    return counts


# read_file shows each line as "    19\t<line>"; small models often copy that number into old_string.
_LINE_NUMBER = re.compile(r"^ *\d+\t")


def _not_found(text: str, old: str, path: str) -> str:
    """Why old_string didn't match, as specifically as we can tell. "Copy the text exactly" alone isn't enough: small
    models send the same wrong text again and again without knowing what's wrong with it."""
    msg = f"old_string wasn't found in {path}."
    olds = old.split("\n")
    filled = [line for line in olds if line.strip()]
    if filled and all(_LINE_NUMBER.match(line) for line in filled):
        return (f"{msg} It starts with a line number and a tab ({olds[0][:12]!r}). read_file shows those in front of "
                "each line, but they aren't part of the file: copy only the text after the tab.")
    if not filled:
        return f"{msg} It's only blank space; put the exact text to replace in it."
    lines = text.split("\n")
    want = [line.strip() for line in olds]
    for i in range(len(lines) - len(want) + 1):
        if [line.strip() for line in lines[i:i + len(want)]] == want:
            found = "\n".join(lines[i:i + len(want)])[:1500]
            return (f"{msg} The same text is at line {i + 1}, but with different indentation or spacing. These are the "
                    f"exact lines in the file; copy them into old_string as they are:\n{found}")
    first = next((line.strip() for line in olds if line.strip()), "")
    starts = [i for i, line in enumerate(lines) if first and line.strip() == first]
    if starts and len(filled) > 1:
        n = starts[0] + 1
        return (f"{msg} Its first line is at line {n}, but the lines after it don't match the file. Read the file from "
                f"line {n} again (read_file with offset={n}) and copy the lines exactly.")
    return f"{msg} Read the file again and copy the text exactly, including indentation."


def _apply_edit(text, old, new, replace_all, path):
    if not old:
        raise ToolError("old_string is empty. Put the exact text to replace in it (to add text, include a line next to "
                        "where it goes), or use write_file for a new file.")
    if old == new:
        raise ToolError("old_string and new_string are the same.")
    n = text.count(old)
    if n == 0:
        raise ToolError(_not_found(text, old, path))
    if n > 1 and not replace_all:
        raise ToolError(f"old_string appears {n} times in {path}. Add more surrounding text to make it unique, "
                        "or set replace_all.")
    return text.replace(old, new) if replace_all else text.replace(old, new, 1), n if replace_all else 1


def edit_file(pid, path, old_string, new_string, replace_all=False):
    p = _resolve(pid, path)
    [n] = _edit(p, path, [(old_string, new_string, replace_all)])
    return f"Edited {_rel(pid, p)} ({n} replacement{'s' if n != 1 else ''})."


def multi_edit(pid, path, edits):
    p = _resolve(pid, path)
    counts = _edit(p, path, [(e["old_string"], e["new_string"], e.get("replace_all", False)) for e in edits],
                   numbered=True)
    return f"Edited {_rel(pid, p)} ({len(edits)} edits, {sum(counts)} replacements)."


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
        lines = _lines(data.decode("utf-8", errors="replace"))
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
        # Icons, images and menus leave bullets and headings with nothing in them; they only waste the model's memory.
        t = re.sub(r"(?m)^ ?(-|#+) ?$", "", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()


# An honest name with a link: sites like Wikipedia refuse clients that pretend to be a browser.
FETCH_HEADERS = {"User-Agent": "wanna.sh-code-agent/0.1 (+https://github.com/wanna-sh/wanna)"}
FETCH_MAX_BYTES = 25 * 1024 * 1024
FETCH_MAX_CHARS = 20_000
FETCH_MAX_REDIRECTS = 5


def _fetch_target(pid, url):
    """Check where a link points before fetching it.

    web_fetch runs on this computer, not in the sandbox, so local and private-network addresses (wanna.sh's own
    API, a router page) are refused. The one exception is the project's own app: "localhost:3000" is sent to the
    port its sandbox publishes, so the agent can check what it built. Without a project (chat), there's no exception.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("Only http and https links can be fetched.")
    host = parts.hostname
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addrs = {ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except (socket.gaierror, UnicodeError):
        raise ToolError(f"Couldn't find the website {host}. Check the link.")
    addrs = {a.ipv4_mapped or a if isinstance(a, ipaddress.IPv6Address) else a for a in addrs}
    if all(a.is_global for a in addrs):
        return url
    if pid and all(a.is_loopback for a in addrs):
        try:
            published = sandbox.ports(pid)  # container port -> port on this computer
        except (OSError, subprocess.SubprocessError):
            published = {}
        host_port = published.get(port) or (port if port in published.values() else None)
        if host_port:
            app_port = port if port in published else next(c for c, h in published.items() if h == port)
            inside = sandbox.app_url(pid, app_port)  # wanna.sh in Docker: go over the shared network
            base = inside or f"{parts.scheme}://127.0.0.1:{host_port}"
            return base + urlunsplit(("", "", parts.path, parts.query, ""))
        open_ports = ", ".join(str(p) for p in sorted(published)) or "none yet"
        raise ToolError(
            f"web_fetch can only reach this computer through the project's own app ports ({open_ports}). "
            "Start a server on one of 3000, 5173, 8000 or 8080 in the sandbox, or use bash with curl inside it."
        )
    raise ToolError(f"{host} is a local or private network address, which web_fetch doesn't open.")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ToolError("That PDF is password protected.")
        parts, total = [], 0
        for i, page in enumerate(reader.pages, 1):
            t = (page.extract_text() or "").strip()
            parts.append(f"[page {i}]\n{t}")
            total += len(t)
            if total > FETCH_MAX_CHARS:
                break
    except PdfReadError as e:
        raise ToolError(f"Couldn't read that PDF: {e}")
    text = "\n\n".join(parts)
    if total == 0:
        raise ToolError("That PDF has no selectable text (it may be scanned pictures of pages).")
    return f"PDF, {len(reader.pages)} pages\n\n{text}"


def web_fetch(pid, url):
    url = (url or "").strip()
    try:
        with httpx.Client(timeout=30, headers=FETCH_HEADERS) as client:
            # Redirects are followed by hand so every hop gets the same address check.
            for _ in range(FETCH_MAX_REDIRECTS + 1):
                target = _fetch_target(pid, url)
                with client.stream("GET", target) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = urljoin(url, r.headers["location"])
                        continue
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        if len(data) > FETCH_MAX_BYTES:
                            raise ToolError(f"{url} is over 25 MB, too big to read.")
                    break
            else:
                raise ToolError(f"{url} redirects too many times.")
    except httpx.HTTPError as e:
        raise ToolError(f"Couldn't fetch {url}: {e}")
    if r.status_code >= 400:
        raise ToolError(f"{url} returned HTTP {r.status_code}." + (
            " The site blocks automated visitors; try another source." if r.status_code in (401, 403, 429) else ""))
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or data[:5] == b"%PDF-":
        body = _pdf_text(data)
    else:
        text = data.decode(r.encoding or "utf-8", errors="replace")
        if "html" in ctype:
            parser = _Text()
            parser.feed(text)
            body = parser.text()
        elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype or "javascript" in ctype:
            body = text
        else:
            raise ToolError(f"{url} isn't a text page or PDF ({ctype or 'unknown type'}).")
    clipped = body[:FETCH_MAX_CHARS]
    return f"URL: {url}\n\n{clipped}" + (
        f"\n\n[page cut off at {FETCH_MAX_CHARS:,} characters]" if len(body) > FETCH_MAX_CHARS else "")


KNOWLEDGE_SCHEMA = _fn(
    "search_knowledge",
    "Search the user's own documents attached to this project (specs, notes, manuals, reference docs). Returns the "
    "most relevant passages with their document names. Use it whenever the request may depend on those documents.",
    {"query": {"type": "string", "description": "What to look for, as a question or keywords."}},
    ["query"],
)


def schemas_for(project: dict) -> list[dict]:
    """The tools the agent gets: search_knowledge only when the project has knowledge libraries, plus the person's
    custom tools that are on."""
    from .. import usertools

    return SCHEMAS + ([KNOWLEDGE_SCHEMA] if project.get("knowledge") else []) + usertools.schemas()


def search_knowledge(pid, query):
    from ..knowledge.search import search_blocking
    from .projects import get as get_project

    libraries = (get_project(pid) or {}).get("knowledge") or []
    if not libraries:
        raise ToolError("This project has no knowledge libraries. The user can add some in project settings.")
    results = search_blocking(query, libraries, k=6)
    if not results:
        return "No matching passages in the project's documents."
    parts = []
    for n, r in enumerate(results, 1):
        where = r["document"] + (f", page {r['page']}" if r.get("page") else "") + (f", {r['heading']}" if r["heading"] else "")
        parts.append(f"[{n}] {where}\n{r['text'].strip()}")
    return "\n\n".join(parts)


def web_search(pid, query, max_results=8):
    """Brave (with a key), local SearXNG, or DuckDuckGo as a last resort. See code/search.py."""
    from . import search

    try:
        results, provider = search.search(query, max_results)
    except search.SearchError as e:
        raise ToolError(f"{e} You can still use web_fetch on a documentation page you know.")
    lines = [f"{r['title']}\n{r['url']}\n{r['snippet']}".strip() for r in results]
    return f"Results from {provider}:\n\n" + "\n\n".join(lines)


# --- dispatch ----------------------------------------------------------------------------------------------------

FUNCS = {
    "read_file": read_file, "write_file": write_file, "edit_file": edit_file, "multi_edit": multi_edit,
    "list_files": list_files, "glob": glob, "grep": grep, "bash": bash, "bash_output": bash_output,
    "kill_shell": kill_shell, "web_fetch": web_fetch, "web_search": web_search, "search_knowledge": search_knowledge,
}


def call(pid: str, name: str, args: dict, cancel: threading.Event | None = None) -> str:
    """Run a tool and return text for the model. Problems come back as text the model can act on."""
    fn = FUNCS.get(name)
    if fn is None:
        from .. import usertools

        if usertools.is_tool(name):
            r = usertools.run(name, args)
            printed = f"\n[printed]\n{r['printed']}" if r.get("printed") else ""
            return (r["result"] if r["ok"] else f"Error: {r['error']}") + printed
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
