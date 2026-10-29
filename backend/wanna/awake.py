"""Keep the computer from going to sleep while wanna.sh is downloading.

Only idle sleep is held off: the screen still locks and turns off, and closing a laptop's lid or choosing Sleep still
puts it to sleep. Each system's own mechanism is used, and released as soon as the last download finishes:

- macOS: `caffeinate -i`, which also lets go by itself if wanna.sh exits;
- Windows: a power request (SetThreadExecutionState with ES_SYSTEM_REQUIRED);
- Linux: a systemd-inhibit sleep lock, where systemd is running (not in Docker or most WSL setups).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading

log = logging.getLogger("wanna.awake")

_lock = threading.Lock()
_holders = 0
_release = None  # stops whatever is keeping the computer awake


def hold() -> None:
    """One more thing needs the computer awake (calls nest; pair each with let_go)."""
    global _holders, _release
    with _lock:
        _holders += 1
        if _holders == 1:
            try:
                _release = _start()
            except Exception as e:  # never let this get in the way of the download itself
                log.warning("Couldn't keep the computer awake: %s", e)
                _release = None


def let_go() -> None:
    global _holders, _release
    with _lock:
        _holders = max(0, _holders - 1)
        if _holders == 0 and _release:
            try:
                _release()
            except Exception as e:
                log.warning("Couldn't let the computer sleep again: %s", e)
            _release = None


def _start():
    if sys.platform == "darwin":
        return _stopper(subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())]))
    if os.name == "nt":
        return _windows_power_request()
    if os.environ.get("WANNA_IN_DOCKER") or not shutil.which("systemd-inhibit"):
        return None
    proc = subprocess.Popen(
        ["systemd-inhibit", "--what=sleep", "--mode=block", "--who=wanna.sh", "--why=Downloading a model",
         "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return _stopper(proc)


def _stopper(proc: subprocess.Popen):
    def stop():
        proc.terminate()
        proc.wait(timeout=5)  # collect it, even if it had already exited (systemd-inhibit can be refused)

    return stop


def _windows_power_request():
    import ctypes

    es_continuous, es_system_required = 0x80000000, 0x00000001
    done = threading.Event()

    def keep():
        # The request belongs to the thread that makes it, so this thread holds it until told to stop.
        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_state.restype = ctypes.c_uint
        set_state.argtypes = [ctypes.c_uint]
        set_state(es_continuous | es_system_required)
        done.wait()
        set_state(es_continuous)

    threading.Thread(target=keep, daemon=True, name="keep-awake").start()
    return done.set
