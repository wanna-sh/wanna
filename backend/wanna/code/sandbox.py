"""One Docker container per project. Only the project folder is mounted, at /workspace.

Commands run as the host user (so files stay editable outside the container). A handful of common
web ports are published on free host ports so dev servers can be previewed from the browser.

Each sandbox gets a firewall in its own network namespace (see FIREWALL): it can reach the internet, but not
this computer, the local network or wanna.sh itself. The sandbox has no network capabilities, so code running
in it can't change those rules.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from ..config import DOCKER_NETWORK, host_path
from .projects import folder

log = logging.getLogger("wanna.code.sandbox")

# Bump the tag when the Dockerfile changes, so existing installs build the new image.
IMAGE = os.environ.get("WANNA_SANDBOX_IMAGE", "wanna-sandbox:2")
DOCKERFILE_DIR = Path(__file__).parent  # wanna/code/Dockerfile
WORKDIR = "/workspace"
PREVIEW_PORTS = (3000, 5173, 8000, 8080)  # common dev-server ports inside the container
MAX_OUTPUT = 30_000

_lock = threading.Lock()
_build_lock = threading.Lock()
_build = {"running": False, "error": None}
_firewalled: set[str] = set()  # containers whose firewall was applied by this process

# Outgoing connections the sandbox may not open: this computer (Docker's gateway, Docker Desktop's
# host.docker.internal), the local network, and link-local/cloud metadata addresses. Replies to connections made
# *to* the sandbox (wanna.sh checking a preview port) and DNS are allowed.
FIREWALL = r"""
set -e
for ipt in iptables ip6tables; do
  case $ipt in
    iptables) nets="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10" ;;
    ip6tables) nets="fc00::/7 fe80::/10"; $ipt -L >/dev/null 2>&1 || continue ;;
  esac
  $ipt -N WANNA_OUT 2>/dev/null || $ipt -F WANNA_OUT
  $ipt -C OUTPUT -j WANNA_OUT 2>/dev/null || $ipt -I OUTPUT -j WANNA_OUT
  $ipt -A WANNA_OUT -o lo -j RETURN
  $ipt -A WANNA_OUT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  $ipt -A WANNA_OUT -p udp --dport 53 -j RETURN
  $ipt -A WANNA_OUT -p tcp --dport 53 -j RETURN
  for net in $nets; do $ipt -A WANNA_OUT -d "$net" -j REJECT; done
done
"""


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
    img = _image_exists()
    if not img:
        build_image()
    message = None
    if not img:
        message = (f"Couldn't prepare the code sandbox: {_build['error']}" if _build["error"] and not _build["running"]
                   else "The code sandbox is being prepared. This happens once and takes a few minutes.")
    return {"docker": True, "image": img, "version": r.stdout.strip(), "message": message}


def _image_exists() -> bool:
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15).returncode == 0


def build_image(wait: bool = False) -> None:
    """Build the sandbox image from wanna/code/Dockerfile in the background (once). With wait, block until done."""
    with _build_lock:
        start = not _build["running"] and not _image_exists()
        if start:
            _build.update(running=True, error=None)
            threading.Thread(target=_build_image, daemon=True, name="sandbox-build").start()
    if wait:
        deadline = time.time() + 1200
        while _build["running"] and time.time() < deadline:
            time.sleep(2)


def _build_image() -> None:
    log.info("Building the code sandbox image %s", IMAGE)
    try:
        r = subprocess.run(["docker", "build", "-t", IMAGE, str(DOCKERFILE_DIR)], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            _build["error"] = (r.stderr or r.stdout).strip()[-300:]
            log.error("Sandbox image build failed: %s", _build["error"])
    except (OSError, subprocess.TimeoutExpired) as e:
        _build["error"] = str(e)
    finally:
        _build["running"] = False


def firewall(name: str) -> None:
    """Apply FIREWALL inside the container's network namespace, from a short-lived helper with NET_ADMIN.

    The helper shares only the network namespace; the sandbox itself never gets NET_ADMIN, so it can't undo this.
    """
    r = subprocess.run(
        ["docker", "run", "--rm", "--network", f"container:{name}", "--cap-add", "NET_ADMIN", "--user", "0",
         "--entrypoint", "sh", IMAGE, "-c", FIREWALL],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        # Without the firewall the sandbox could reach this computer, so don't let it run.
        subprocess.run(["docker", "stop", "-t", "1", name], capture_output=True, timeout=60)
        raise SandboxError(f"Couldn't set up the sandbox's network protection: {r.stderr.strip()[-300:]}")
    _firewalled.add(name)


def _name(pid: str) -> str:
    return f"wanna-code-{pid}"


def network_args() -> list[str]:
    """`docker run` flags that put a container on the network shared with wanna.sh, when it runs in Docker."""
    return ["--network", DOCKER_NETWORK] if DOCKER_NETWORK else []


def join_network(container: str) -> None:
    """Connect an existing container (e.g. created before Code was turned on in Docker) to the shared network."""
    if not DOCKER_NETWORK:
        return
    r = subprocess.run(["docker", "network", "connect", DOCKER_NETWORK, container], capture_output=True, text=True, timeout=30)
    if r.returncode != 0 and "already exists" not in r.stderr:
        log.warning("couldn't connect %s to %s: %s", container, DOCKER_NETWORK, r.stderr.strip()[-200:])


def app_url(pid: str, port: int) -> str | None:
    """How wanna.sh reaches a preview port inside the project's container, when it runs in Docker itself."""
    return f"http://{_name(pid)}:{port}" if DOCKER_NETWORK else None


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
                join_network(name)
                if name not in _firewalled:  # e.g. started by an earlier version, or before a restart
                    firewall(name)
                return name
            if subprocess.run(["docker", "start", name], capture_output=True, timeout=60).returncode == 0:
                join_network(name)
                firewall(name)  # a restarted container has a fresh network namespace
                return name
            # A container that won't start (e.g. left half-created) is replaced below.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        status = docker_status()
        if status["docker"] and not status["image"]:
            build_image(wait=True)  # first use: build it now (a few minutes) rather than fail
            status = docker_status()
        if not status["docker"] or not status["image"]:
            raise SandboxError(status["message"])
        cmd = [
            # --init reaps finished processes, so background jobs report "finished" correctly.
            "docker", "run", "-d", "--init", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{host_path(folder(pid))}:{WORKDIR}",
            "-w", WORKDIR,
            "--memory", "4g", "--cpus", "4", "--pids-limit", "512",
            "--label", "wanna.code=1",
            *network_args(),
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
        firewall(name)
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
