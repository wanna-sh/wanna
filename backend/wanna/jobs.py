"""Background generation jobs (images, video, audio) with live progress for the UI."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import httpx

from . import db
from .workers.manager import manager

log = logging.getLogger("wanna.jobs")

KIND_FOR_TASK = {"image": "image", "video": "video", "speech": "audio", "sound": "audio", "transcribe": "text"}


class Job:
    def __init__(self, task: str, model: dict, params: dict, prompt: str):
        self.id = uuid.uuid4().hex[:16]
        self.task = task
        self.model = model
        self.params = params
        self.prompt = prompt
        self.status = "queued"  # queued | loading | running | completed | failed
        self.error: str | None = None
        self.result: dict | None = None
        self.generation: dict | None = None
        self.created_at = time.time()
        self.completed_at: float | None = None
        self.step = 0
        self.total_steps = int(params.get("steps") or 0)
        self.done = asyncio.Event()

    def to_dict(self) -> dict:
        progress = 0.0
        if self.status == "completed":
            progress = 1.0
        elif self.status == "running" and self.total_steps:
            progress = min(0.99, self.step / self.total_steps)
        return {
            "id": self.id,
            "task": self.task,
            "model": self.model["id"],
            "status": self.status,
            "error": self.error,
            "progress": progress,
            "step": self.step,
            "total_steps": self.total_steps,
            "prompt": self.prompt,
            "result": self.result,
            "generation": self.generation,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


_jobs: dict[str, Job] = {}


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def recent(limit: int = 20) -> list[dict]:
    return [j.to_dict() for j in sorted(_jobs.values(), key=lambda j: -j.created_at)[:limit]]


def submit(task: str, model: dict, params: dict, prompt: str = "") -> Job:
    job = Job(task, model, params, prompt)
    _jobs[job.id] = job
    asyncio.create_task(_run(job))
    if len(_jobs) > 200:
        for old in sorted(_jobs.values(), key=lambda j: j.created_at)[:50]:
            _jobs.pop(old.id, None)
    return job


async def run_now(task: str, model: dict, params: dict, prompt: str = "") -> Job:
    job = submit(task, model, params, prompt)
    await job.done.wait()
    return job


async def _run(job: Job) -> None:
    worker = None
    try:
        job.status = "loading"
        worker = await manager.ensure_ready(job.model)
        job.status = "running"
        poller = asyncio.create_task(_poll_progress(job, worker.url))
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                r = await c.post(f"{worker.url}/run", json=job.params)
        finally:
            poller.cancel()
        if r.status_code != 200:
            raise RuntimeError(_detail(r))
        job.result = r.json()
        worker.last_used = time.time()
        kind = KIND_FOR_TASK[job.task]
        if job.result.get("files"):
            stored = {k: v for k, v in job.params.items() if k not in ("image", "file")}
            stored["seed"] = job.result.get("seed", stored.get("seed"))
            job.generation = db.add_generation(job.id, kind, job.model["id"], job.prompt, stored, job.result["files"])
        job.status = "completed"
    except Exception as e:
        log.warning("job %s failed: %s", job.id, e)
        # Prefer the worker's own explanation (e.g. stopped for lack of memory) over a raw connection error.
        job.status, job.error = "failed", (worker.error if worker and worker.error else str(e))
    finally:
        job.completed_at = time.time()
        job.done.set()


async def _poll_progress(job: Job, url: str) -> None:
    async with httpx.AsyncClient(timeout=2) as c:
        while True:
            await asyncio.sleep(0.5)
            try:
                st = (await c.get(f"{url}/health")).json()
                job.step = st.get("step", 0)
                if st.get("total_steps"):
                    job.total_steps = st["total_steps"]
            except Exception:
                pass


def _detail(r: httpx.Response) -> str:
    try:
        return r.json().get("detail") or r.text
    except Exception:
        return r.text
