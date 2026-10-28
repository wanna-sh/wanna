"""One Docker container per project. Only the project folder is mounted, at /workspace.

Commands run as the host user (so files stay editable outside the container). A handful of common
web ports are published on free host ports so dev servers can be previewed from the browser.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid

from .projects import folder

log = logging.getLogger("wanna.code.sandbox")

IMAGE = os.environ.get("WANNA_SANDBOX_IMAGE", "wanna-sandbox:1")
WORKDIR = "/workspace"
PREVIEW_PORTS = (3000, 5173, 8000, 8080)  # common dev-server ports inside the container
MAX_OUTPUT = 30_000

_lock = threading.Lock()


class SandboxError(Exception):
    pass


def docker_status() -> dict:
    """Is Docker usable, and is the sandbox image built?"""
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {"docker": False, "image": False, "message": "Docker isn't installed. Install Docker Desktop to let the agent run commands."}
    if r.returncode != 0:
        return {"docker": False, "image": False, "message": "Docker isn't running. Start Docker Desktop to let the agent run commands."}
    img = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15).returncode == 0
    return {"docker": True, "image": img, "version": r.stdout.strip(),
            "message": None if img else "The code sandbox is being prepared. This happens once."}


def _name(pid: str) -> str:
    return f"wanna-code-{pid}"


def ports(pid: str) -> dict[int, int]:
    """Container port -> host port for a running project container."""
    r = subprocess.run(["docker", "port", _name(pid)], capture_output=True, text=True, timeout=15)
    out = {}
    for line in r.stdout.splitlines():  # "3000/tcp -> 127.0.0.1:49153"
        try:
            left, right = line.split(" -> ")
            out[int(left.split("/")[0])] = int(right.rsplit(":", 1)[1])
        except ValueError:
            continue
    return out


def ensure(pid: str) -> str:
    """Start (or reuse) the project's container. Returns its name."""
    name = _name(pid)
    with _lock:
        state = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True, timeout=20)
        if state.returncode == 0:
            if state.stdout.strip() == "true":
                return name
            if subprocess.run(["docker", "start", name], capture_output=True, timeout=60).returncode == 0:
                return name
            # A container that won't start (e.g. left half-created) is replaced below.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        status = docker_status()
        if not status["docker"] or not status["image"]:
            raise SandboxError(status["message"])
        cmd = [
            # --init reaps finished processes, so background jobs report "finished" correctly.
            "docker", "run", "-d", "--init", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{folder(pid)}:{WORKDIR}",
            "-w", WORKDIR,
            "--memory", "4g", "--cpus", "4", "--pids-limit", "512",
            "--label", "wanna.code=1",
        ]
        for p in PREVIEW_PORTS:
            # Let Docker choose the host port: on Docker Desktop ports are bound on the Windows side,
            # where a port that looks free from WSL may be reserved.
            cmd += ["-p", f"127.0.0.1::{p}"]
        cmd.append(IMAGE)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
            raise SandboxError(f"Couldn't start the sandbox: {r.stderr.strip()[-300:]}")
        return name


def stop(pid: str) -> None:
    subprocess.run(["docker", "rm", "-f", _name(pid)], capture_output=True, timeout=60)


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return text[:half] + f"\n\n[... {len(text) - MAX_OUTPUT} characters cut from the middle ...]\n\n" + text[-half:]


def run(pid: str, command: str, timeout: int = 120, cancel: threading.Event | None = None) -> dict:
    """Run a command to completion in the project's container."""
    name = ensure(pid)
    timeout = max(1, min(int(timeout or 120), 600))
    proc = subprocess.Popen(
        ["docker", "exec", "-w", WORKDIR, name, "bash", "-lc", command],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
    )
    deadline = time.time() + timeout
    while proc.poll() is None:
        if time.time() > deadline or (cancel and cancel.is_set()):
            proc.kill()
            # Also stop the command inside the container, not just the docker client.
            subprocess.run(["docker", "exec", name, "pkill", "-f", command[:60]], capture_output=True, timeout=10)
            out = proc.stdout.read() if proc.stdout else ""
            why = "was stopped" if cancel and cancel.is_set() else f"timed out after {timeout} seconds"
            return {"exit_code": None, "output": _clip(out), "note": f"The command {why}. "
                    "For servers or long jobs, run it with background set to true."}
        time.sleep(0.1)
    out = proc.stdout.read() if proc.stdout else ""
    return {"exit_code": proc.returncode, "output": _clip(out)}


# --- background shells ------------------------------------------------------------------------

_shells: dict[str, dict] = {}


def start_background(pid: str, command: str) -> dict:
    name = ensure(pid)
    sid = uuid.uuid4().hex[:8]
    log_path = f"/tmp/wanna-shell-{sid}.log"
    # setsid gives the job its own process group so kill_shell can stop it and its children.
    inner = f"setsid bash -lc {_quote(command)} > {log_path} 2>&1 & echo $!"
    r = subprocess.run(["docker", "exec", "-w", WORKDIR, name, "bash", "-c", inner], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise SandboxError(r.stderr.strip() or "Couldn't start the command.")
    _shells[sid] = {"pid": pid, "proc": r.stdout.strip(), "log": log_path, "command": command, "read": 0}
    return {"shell_id": sid, "note": "Running in the background. Use bash_output to read its output."}


def background_output(sid: str) -> dict:
    sh = _shells.get(sid)
    if not sh:
        return {"error": f"No background shell {sid}."}
    name = _name(sh["pid"])
    alive = subprocess.run(["docker", "exec", name, "kill", "-0", sh["proc"]], capture_output=True, timeout=10).returncode == 0
    r = subprocess.run(["docker", "exec", name, "cat", sh["log"]], capture_output=True, text=True, errors="replace", timeout=20)
    new = r.stdout[sh["read"]:]
    sh["read"] = len(r.stdout)
    return {"status": "running" if alive else "finished", "new_output": _clip(new)}


def kill_background(sid: str) -> dict:
    sh = _shells.pop(sid, None)
    if not sh:
        return {"error": f"No background shell {sid}."}
    subprocess.run(["docker", "exec", _name(sh["pid"]), "kill", "-TERM", f"-{sh['proc']}"], capture_output=True, timeout=10)
    return {"stopped": sid}


def list_background(pid: str) -> list[dict]:
    return [{"shell_id": k, "command": v["command"]} for k, v in _shells.items() if v["pid"] == pid]


def _quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
