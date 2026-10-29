"""Web search for the Code agent.

In order of preference:
1. Brave Search API, if you added a key in Settings (official API, your own quota).
2. SearXNG, an open-source metasearch engine wanna.sh runs locally in Docker (no account, no key).
   It spreads queries over several engines, so one engine rate-limiting us doesn't stop search.
3. DuckDuckGo's HTML page, as a last resort. It shows a bot check after bursts of searches.
"""

from __future__ import annotations

import html
import logging
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..config import DOCKER_NETWORK, HOME, host_path, load_settings
from .sandbox import join_network, network_args

log = logging.getLogger("wanna.code.search")

# Pinned so a SearXNG update can't change behaviour underneath us.
SEARXNG_IMAGE = "searxng/searxng:2026.10.28-c360868e5"
SEARXNG_CONTAINER = "wanna-searxng"
SEARXNG_DIR = HOME / "searxng"

_lock = threading.Lock()

# What happened last time, for the system check.
status = {"provider": None, "ok_at": None, "error": None, "blocked_at": None}


class SearchError(Exception):
    pass


# --- SearXNG ------------------------------------------------------------------------------------------------

def _write_settings() -> None:
    SEARXNG_DIR.mkdir(parents=True, exist_ok=True)
    path = SEARXNG_DIR / "settings.yml"
    if path.exists():
        return
    path.write_text(
        "# Written by wanna.sh: a private SearXNG used by the Code agent's web_search tool.\n"
        "use_default_settings: true\n"
        "server:\n"
        f"  secret_key: \"{secrets.token_hex(32)}\"\n"
        "  limiter: false          # the limiter protects public instances and needs Valkey; this one is local\n"
        "  public_instance: false\n"
        "  image_proxy: false\n"
        "search:\n"
        "  safe_search: 0\n"
        "  formats:\n"
        "    - html\n"
        "    - json                # the API wanna.sh uses\n"
    )
    path.chmod(0o644)
    SEARXNG_DIR.chmod(0o755)


def searxng_state() -> str:
    """'running', 'stopped', 'missing' (never created) or 'no-docker'."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", SEARXNG_CONTAINER],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "no-docker"
    if r.returncode != 0:
        ok = subprocess.run(["docker", "version"], capture_output=True, timeout=15).returncode == 0
        return "missing" if ok else "no-docker"
    return "running" if r.stdout.strip() == "true" else "stopped"


def _searxng_url() -> str | None:
    if DOCKER_NETWORK:  # wanna.sh runs in Docker: reach SearXNG over the shared network
        join_network(SEARXNG_CONTAINER)
        return f"http://{SEARXNG_CONTAINER}:8080"
    r = subprocess.run(["docker", "port", SEARXNG_CONTAINER, "8080"], capture_output=True, text=True, timeout=15)
    m = re.search(r":(\d+)\s*$", r.stdout.strip().splitlines()[0] if r.stdout.strip() else "")
    return f"http://127.0.0.1:{m.group(1)}" if m else None


def ensure_searxng(timeout: float = 120) -> str:
    """Start the local SearXNG container (creating it the first time) and return its URL once it answers."""
    with _lock:
        state = searxng_state()
        if state == "no-docker":
            raise SearchError("Docker isn't running, so local search (SearXNG) isn't available.")
        if state == "stopped":
            subprocess.run(["docker", "start", SEARXNG_CONTAINER], capture_output=True, timeout=60)
        elif state == "missing":
            _write_settings()
            r = subprocess.run(
                ["docker", "run", "-d", "--name", SEARXNG_CONTAINER, "--label", "wanna.search=1",
                 "-p", "127.0.0.1::8080", "-v", f"{host_path(SEARXNG_DIR)}:/etc/searxng", *network_args(), SEARXNG_IMAGE],
                capture_output=True, text=True, timeout=600,  # the first run downloads the image (~100 MB)
            )
            if r.returncode != 0:
                subprocess.run(["docker", "rm", "-f", SEARXNG_CONTAINER], capture_output=True, timeout=60)
                raise SearchError(f"Couldn't start SearXNG: {r.stderr.strip()[-300:]}")
        url = _searxng_url()
        if not url:
            raise SearchError("SearXNG started but has no port.")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(f"{url}/healthz", timeout=5).status_code == 200:
                    return url
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise SearchError("SearXNG didn't start in time.")


def _searxng(query: str, n: int) -> list[dict]:
    url = ensure_searxng()
    r = httpx.get(f"{url}/search", params={"q": query, "format": "json", "language": "en"}, timeout=30)
    if r.status_code == 403:
        raise SearchError("SearXNG refused JSON requests; its settings.yml needs json under search.formats.")
    r.raise_for_status()
    data = r.json()
    results = [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
               for x in data.get("results", []) if x.get("url")]
    if not results:
        down = [e[0] for e in data.get("unresponsive_engines", [])]
        raise SearchError("SearXNG found nothing" + (f" (engines not answering: {', '.join(down[:5])})" if down else "") + ".")
    return results[:n]


# --- Brave ---------------------------------------------------------------------------------------------------------

def _brave(query: str, n: int, key: str) -> list[dict]:
    r = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": min(n, 20)},
                  headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=20)
    if r.status_code in (401, 403, 422):  # Brave answers an unknown key with 422
        raise SearchError("The Brave Search key in Settings was refused.")
    if r.status_code == 429:
        raise SearchError("The Brave Search key is out of quota or rate limited.")
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("description", "")}
            for x in (r.json().get("web") or {}).get("results", [])][:n]


# --- DuckDuckGo (last resort) ---------------------------------------------------------------------------------------

def _duckduckgo(query: str, n: int) -> list[dict]:
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=20,
                   headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
    if r.status_code == 202 or "anomaly" in r.text[:20000].lower():
        status["blocked_at"] = time.time()
        raise SearchError("DuckDuckGo is asking for a human check after too many searches.")
    out = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         r.text, re.S):
        href, title, snippet = m.groups()
        q = parse_qs(urlparse(html.unescape(href)).query)
        link = unquote(q["uddg"][0]) if "uddg" in q else html.unescape(href)
        if "duckduckgo.com/y.js" in link:
            continue  # ads
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
        out.append({"title": clean(title), "url": link, "snippet": clean(snippet)})
        if len(out) >= n:
            break
    if not out:
        raise SearchError("DuckDuckGo returned no results.")
    return out


# --- entry point --------------------------------------------------------------------------------------------------------

def search(query: str, n: int = 8) -> tuple[list[dict], str]:
    """Search with the best available provider. Returns (results, provider name)."""
    n = max(1, min(int(n or 8), 15))
    key = (load_settings().get("brave_api_key") or "").strip()
    providers = ([("Brave Search", lambda: _brave(query, n, key))] if key else []) + [
        ("SearXNG", lambda: _searxng(query, n)),
        ("DuckDuckGo", lambda: _duckduckgo(query, n)),
    ]
    problems = []
    for name, fn in providers:
        try:
            results = fn()
            status.update(provider=name, ok_at=time.time(), error=None)
            if name != "DuckDuckGo":
                status["blocked_at"] = None
            return results, name
        except (SearchError, httpx.HTTPError, ValueError) as e:
            log.warning("search via %s failed: %s", name, e)
            problems.append(f"{name}: {e}")
    status.update(error="; ".join(problems))
    raise SearchError("Web search isn't working right now. " + " ".join(problems))
