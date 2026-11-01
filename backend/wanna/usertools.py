"""Custom tools: Python functions people write and give to the AI, in Chat, Code and through the API.

A tool is one file in ~/.wanna/tools, named after the tool, with a function called run. Its docstring is what the AI
reads, and its type hints describe the inputs:

    # /// script
    # dependencies = ["requests"]
    # ///

    def run(city: str, units: str = "metric") -> str:
        \"\"\"Get the current weather for a city.

        Args:
            city: The city, e.g. "Paris".
            units: "metric" or "imperial".
        \"\"\"

wanna.sh reads a tool by parsing its file, never by running it, so listing tools from anyone is safe. Tools run in a
Docker sandbox (internet yes; this computer's files and local network no), or, once the person trusts that exact file,
directly on this computer. Trust lives in wanna.sh's own state, not in the file, and editing the file takes it away.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from .config import HOME

log = logging.getLogger("wanna.usertools")

TOOLS_DIR = HOME / "tools"
STATE_PATH = HOME / "tools.json"  # outside the tools folder, which the sandbox can read
HOST_PACKAGES = HOME / "tool-packages"  # packages for trusted tools, kept apart from wanna.sh's own
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
TIMEOUT = 60  # seconds a tool may run
RESULT_LIMIT = 20_000  # characters of a result the AI gets
MARK = "\x1e__wanna_tool_result__"

TEMPLATE = '''def run(text: str, shout: bool = False) -> str:
    """Count the words in a piece of text.

    Args:
        text: The text to count.
        shout: Answer in capital letters.
    """
    answer = f"{len(text.split())} words"
    return answer.upper() if shout else answer
'''

# The script that runs a tool, in the sandbox or on this computer: python -c RUNNER <tool file> [packages folder],
# with the arguments as JSON on stdin. What the tool prints is kept apart from its result.
RUNNER = r"""
import asyncio, contextlib, importlib.util, inspect, io, json, sys, traceback
MARK = "\x1e__wanna_tool_result__"
if len(sys.argv) > 2:
    sys.path.insert(0, sys.argv[2])
args = json.loads(sys.stdin.read() or "{}")
printed = io.StringIO()
try:
    with contextlib.redirect_stdout(printed):
        spec = importlib.util.spec_from_file_location("tool", sys.argv[1])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run(**args)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False, default=str)
    out = {"ok": True, "result": result}
except Exception as e:
    tb = traceback.extract_tb(e.__traceback__)
    where = next((f"line {f.lineno}" for f in reversed(tb) if f.filename == sys.argv[1]), None)
    out = {"ok": False, "error": f"{type(e).__name__}: {e}" + (f" ({where})" if where else "")}
out["printed"] = printed.getvalue()[-4000:]
sys.stdout.write("\n" + MARK + json.dumps(out))
"""

_lock = threading.Lock()
_install_lock = threading.Lock()


class ToolError(Exception):
    """A problem to show the person (bad name, no such tool, ...)."""


# --- reading a tool without running it -----------------------------------------------------------------------------

def reserved_names() -> set[str]:
    """Built-in tool names a custom tool can't take: Chat's web tools and Code's tools."""
    from .code import tools as code_tools

    names = {s["function"]["name"] for s in code_tools.SCHEMAS} | {code_tools.KNOWLEDGE_SCHEMA["function"]["name"]}
    return names | set(code_tools.FUNCS) | {"web_search", "web_fetch"}


_SIMPLE = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "dict": "object",
           "Dict": "object", "list": "array", "List": "array", "tuple": "array", "Tuple": "array", "set": "array"}


def _type_schema(node: ast.expr | None) -> dict:
    """JSON Schema for a type hint, read from the syntax tree. Anything unusual becomes a string."""
    if node is None:
        return {"type": "string"}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):  # "str" written as a string
        try:
            return _type_schema(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return {"type": "string"}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # X | None
        sides = [s for s in (node.left, node.right) if not (isinstance(s, ast.Constant) and s.value is None)]
        return _type_schema(sides[0]) if len(sides) == 1 else {"type": "string"}
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = ast.unparse(node).split(".")[-1]
        return {"type": _SIMPLE[name]} if name in _SIMPLE else ({} if name == "Any" else {"type": "string"})
    if isinstance(node, ast.Subscript):
        base = ast.unparse(node.value).split(".")[-1]
        inner = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if base == "Optional":
            return _type_schema(inner[0])
        if base == "Literal":
            values = [e.value for e in inner if isinstance(e, ast.Constant)]
            kinds = {type(v) for v in values}
            kind = {str: "string", int: "integer", float: "number", bool: "boolean"}.get(kinds.pop()) if len(kinds) == 1 else None
            return {"enum": values, **({"type": kind} if kind else {})}
        if base in ("list", "List", "set", "Set", "tuple", "Tuple", "Sequence"):
            return {"type": "array", "items": _type_schema(inner[0])}
        if base in ("dict", "Dict", "Mapping"):
            return {"type": "object"}
    return {"type": "string"}


_SECTION = re.compile(r"^\s*(Args|Arguments|Parameters|Params|Returns?|Raises|Yields|Examples?|Notes?)\s*:\s*$")


def _read_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """(description, {argument: description}) from a Google-style docstring."""
    lines = doc.splitlines()
    description, args, current, section, indent = [], {}, None, None, None
    for line in lines:
        m = _SECTION.match(line)
        if m:
            section, current = m.group(1).lower(), None
            continue
        if section is None:
            description.append(line)
        elif section in ("args", "arguments", "parameters", "params"):
            item = re.match(r"^(\s*)(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", line)
            if item and (indent is None or len(item.group(1)) <= indent):
                indent = len(item.group(1))
                current = item.group(2).lstrip("*")
                args[current] = item.group(3).strip()
            elif current and line.strip():
                args[current] = (args[current] + " " + line.strip()).strip()
    return "\n".join(description).strip(), args


_SCRIPT_BLOCK = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


def _dependencies(source: str) -> list[str]:
    """Packages from the standard inline script metadata (PEP 723): a "# /// script" block with dependencies."""
    import tomllib

    for m in _SCRIPT_BLOCK.finditer(source):
        if m.group("type") != "script":
            continue
        toml = "".join(line[2:] if line.startswith("# ") else line[1:] for line in m.group("content").splitlines(True))
        try:
            deps = tomllib.loads(toml).get("dependencies") or []
        except tomllib.TOMLDecodeError as e:
            raise ToolError(f"The # /// script block isn't valid: {e}")
        if not all(isinstance(d, str) for d in deps):
            raise ToolError("dependencies in the # /// script block must be a list of package names.")
        return deps
    return []


def parse(name: str, source: str) -> dict:
    """What the AI is told about a tool: its description and inputs, as an OpenAI function schema."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ToolError(f"Python can't read line {e.lineno}: {e.msg}.")
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "run"), None)
    if fn is None:
        raise ToolError("A tool needs a function called run. Its inputs are what the AI fills in.")
    description, arg_docs = _read_docstring(ast.get_docstring(fn) or "")
    if not description:
        raise ToolError("Describe what the tool does in run's docstring: the AI decides when to use it from that.")
    a = fn.args
    if a.vararg or a.kwarg:
        raise ToolError("run can't take *args or **kwargs: name each input, so the AI knows what to give it.")
    positional = a.posonlyargs + a.args
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    params = list(zip(positional, defaults)) + list(zip(a.kwonlyargs, a.kw_defaults))
    properties, required = {}, []
    for arg, default in params:
        schema = _type_schema(arg.annotation)
        if arg_docs.get(arg.arg):
            schema["description"] = arg_docs[arg.arg]
        if default is None:
            required.append(arg.arg)
        elif isinstance(default, ast.Constant) and default.value is not None:
            schema["default"] = default.value
        properties[arg.arg] = schema
    return {
        "type": "function",
        "function": {"name": name, "description": description,
                     "parameters": {"type": "object", "properties": properties, "required": required}},
    }


# --- the tools folder and wanna.sh's state for it --------------------------------------------------------------------

def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _path(name: str):
    if not NAME_RE.match(name or ""):
        raise ToolError("A tool's name uses lowercase letters, digits and underscores, starting with a letter "
                        "(up to 48), like get_weather.")
    return TOOLS_DIR / f"{name}.py"


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _describe(name: str, source: str, settings: dict) -> dict:
    out = {"name": name, "path": str(TOOLS_DIR / f"{name}.py"), "enabled": settings.get("enabled", True),
           "trusted": False, "trust_lost": False, "schema": None, "description": "", "dependencies": [], "error": None}
    if name in reserved_names():
        out["error"] = f"{name} is the name of a built-in tool. Rename the file."
    try:
        out["schema"] = parse(name, source)
        out["description"] = out["schema"]["function"]["description"]
        out["dependencies"] = _dependencies(source)
    except ToolError as e:
        out["error"] = out["error"] or str(e)
    trusted = settings.get("trusted_digest")
    out["trusted"] = bool(trusted) and trusted == _digest(source)
    out["trust_lost"] = bool(trusted) and not out["trusted"]  # edited since it was trusted
    return out


def list_tools() -> list[dict]:
    TOOLS_DIR.mkdir(exist_ok=True)
    settings = _load_state().get("tools", {})
    out = []
    for p in sorted(TOOLS_DIR.glob("*.py")):
        if not NAME_RE.match(p.stem):
            continue
        try:
            source = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            out.append({"name": p.stem, "path": str(p), "enabled": False, "trusted": False, "trust_lost": False,
                        "schema": None, "description": "", "dependencies": [], "error": f"Can't read the file: {e}"})
            continue
        out.append(_describe(p.stem, source, settings.get(p.stem, {})))
    return out


def get(name: str) -> dict:
    p = _path(name)
    if not p.exists():
        raise ToolError(f"There's no tool called {name}.")
    source = p.read_text(encoding="utf-8")
    return {**_describe(name, source, _load_state().get("tools", {}).get(name, {})), "source": source}


def save(name: str, source: str, old_name: str | None = None) -> dict:
    """Write a tool's file (renaming it from old_name). Problems in the code are reported, not refused, so work in
    progress can be saved; a tool with a problem isn't given to the AI."""
    p = _path(name)
    if name in reserved_names():
        raise ToolError(f"{name} is the name of a built-in tool. Choose another name.")
    TOOLS_DIR.mkdir(exist_ok=True)
    with _lock:
        if old_name and old_name != name:
            old = _path(old_name)
            if p.exists():
                raise ToolError(f"There's already a tool called {name}.")
            state = _load_state()
            tools = state.setdefault("tools", {})
            if old_name in tools:
                tools[name] = tools.pop(old_name)
                _save_state(state)
            old.unlink(missing_ok=True)
        p.write_text(source, encoding="utf-8")
    return get(name)


def delete(name: str) -> None:
    p = _path(name)
    with _lock:
        p.unlink(missing_ok=True)
        state = _load_state()
        state.get("tools", {}).pop(name, None)
        _save_state(state)


def configure(name: str, enabled: bool | None = None, trusted: bool | None = None) -> dict:
    """Turn a tool on or off, or trust it to run on this computer. Trust is for the file as it is now."""
    tool = get(name)
    with _lock:
        state = _load_state()
        settings = state.setdefault("tools", {}).setdefault(name, {})
        if enabled is not None:
            settings["enabled"] = bool(enabled)
        if trusted is not None:
            settings["trusted_digest"] = _digest(tool["source"]) if trusted else None
        _save_state(state)
    return get(name)


def schemas(names: list[str] | None = None) -> list[dict]:
    """The function schemas of the tools the AI may use: enabled, free of problems, and in `names` if given. Trained
    tasks switched on for Chat come too (see tasks.py)."""
    from . import tasks

    mine = [t["schema"] for t in list_tools() if t["enabled"] and not t["error"] and t["schema"]]
    return [s for s in mine + tasks.tool_schemas() if names is None or s["function"]["name"] in names]


def is_tool(name: str) -> bool:
    from . import tasks

    return any(t["name"] == name for t in list_tools()) or tasks.is_tool(name)


def is_trusted(name: str) -> bool:
    from . import tasks

    # A trained task runs wanna.sh's own code on its own model, never the person's code: nothing to sandbox.
    return any(t["name"] == name and t["trusted"] for t in list_tools()) or tasks.is_tool(name)


# --- running a tool --------------------------------------------------------------------------------------------------

def run(name: str, arguments: dict | str | None, *, test: bool = False) -> dict:
    """Run a tool. Returns {"ok", "result" or "error", "printed", "seconds", "where"}. With test, it also runs when
    turned off (for the Test button)."""
    started = time.time()
    from . import tasks

    if tasks.is_tool(name):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as e:
                return {"ok": False, "error": f"The arguments aren't valid JSON: {e}", "printed": "", "seconds": 0.0,
                        "where": None}
        r = tasks.run_tool(name, arguments if isinstance(arguments, dict) else {})
        return {**r, "printed": "", "seconds": round(time.time() - started, 2), "where": "computer"}
    try:
        tool = get(name)
    except ToolError as e:
        return {"ok": False, "error": str(e), "printed": "", "seconds": 0.0, "where": None}
    if tool["error"]:
        return {"ok": False, "error": f"{name} has a problem: {tool['error']}", "printed": "", "seconds": 0.0, "where": None}
    if not tool["enabled"] and not test:
        return {"ok": False, "error": f"{name} is turned off.", "printed": "", "seconds": 0.0, "where": None}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"The arguments aren't valid JSON: {e}", "printed": "", "seconds": 0.0, "where": None}
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "The arguments must be a JSON object.", "printed": "", "seconds": 0.0, "where": None}
    where = "computer" if tool["trusted"] else "sandbox"
    try:
        if where == "computer":
            code, out, err = _run_here(tool, arguments)
        else:
            code, out, err = _run_sandboxed(tool, arguments)
    except Exception as e:  # Docker missing, a package that won't install, ...
        return {"ok": False, "error": str(e), "printed": "", "seconds": round(time.time() - started, 2), "where": where}
    result = _read_result(code, out, err)
    result.update(seconds=round(time.time() - started, 2), where=where)
    if result.get("ok") and len(result["result"]) > RESULT_LIMIT:
        result["result"] = result["result"][:RESULT_LIMIT] + f"\n[cut off: the result was {len(result['result'])} characters]"
    return result


def _read_result(code: int | None, out: str, err: str) -> dict:
    if code is None:
        return {"ok": False, "error": f"The tool took longer than {TIMEOUT} seconds and was stopped.", "printed": out[-4000:]}
    if MARK in out:
        before, _, payload = out.rpartition(MARK)
        try:
            result = json.loads(payload)
            result["printed"] = (before.strip() + "\n" + result.get("printed", "")).strip()
            return result
        except json.JSONDecodeError:
            pass
    detail = (err or out).strip()[-1500:]
    return {"ok": False, "error": f"The tool stopped unexpectedly (exit code {code}). {detail}".strip(), "printed": ""}


def _run_sandboxed(tool: dict, arguments: dict) -> tuple[int | None, str, str]:
    from .code import sandbox

    _ensure_packages(tool["dependencies"], sandboxed=True)
    return sandbox.exec_tools(TOOLS_DIR, ["python3", "-c", RUNNER, f"/tools/{tool['name']}.py", "/packages"],
                              json.dumps(arguments), TIMEOUT)


def _run_here(tool: dict, arguments: dict) -> tuple[int | None, str, str]:
    _ensure_packages(tool["dependencies"], sandboxed=False)
    with tempfile.TemporaryDirectory(prefix="wanna-tool-") as work:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            r = subprocess.run([sys.executable, "-I", "-c", RUNNER, tool["path"], str(HOST_PACKAGES)],
                               input=json.dumps(arguments), capture_output=True, text=True, errors="replace",
                               cwd=work, timeout=TIMEOUT, **kwargs)
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return None, out, ""
    return r.returncode, r.stdout, r.stderr


def _ensure_packages(deps: list[str], sandboxed: bool) -> None:
    """Install the packages a tool asks for, once: in the sandbox's packages volume, or for trusted tools in their own
    folder on this computer (never into wanna.sh's environment)."""
    if not deps:
        return
    key = "sandbox" if sandboxed else "computer"
    with _install_lock:
        state = _load_state()
        installed = set(state.get("packages", {}).get(key, []))
        missing = [d for d in deps if d not in installed]
        if not missing:
            return
        log.info("Installing packages for custom tools (%s): %s", key, ", ".join(missing))
        if sandboxed:
            from .code import sandbox

            code, out, err = sandbox.exec_tools(TOOLS_DIR, ["pip", "install", "--quiet", "--target", "/packages", *missing],
                                                timeout=600, root=True)
        else:
            from .addons import _uv

            # uv (from the desktop app or the installer), else pip if this Python has it.
            uv = _uv()
            if uv:
                cmd = [uv, "pip", "install", "--python", sys.executable, "--target", str(HOST_PACKAGES), *missing]
            elif importlib.util.find_spec("pip"):
                cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(HOST_PACKAGES), *missing]
            else:
                raise ToolError("Installing this tool's packages needs uv, which wanna.sh's installer sets up. "
                                "Run the installer again.")
            HOST_PACKAGES.mkdir(exist_ok=True)
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600, **kwargs)
            code, out, err = r.returncode, r.stdout, r.stderr
        if code != 0:
            raise ToolError(f"Couldn't install {', '.join(missing)}: {(err or out).strip()[-600:]}")
        state = _load_state()
        state.setdefault("packages", {})[key] = sorted(installed | set(missing))
        _save_state(state)
