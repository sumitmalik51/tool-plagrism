"""In-process registry for long-running scan jobs.

Each job wraps an ``asyncio.Task`` that executes the analysis pipeline.
Progress events flow through the existing ``app.services.progress`` module,
so the SSE endpoint at ``/api/v1/scan-progress/{document_id}`` keeps working.

Limitations (acceptable for V1):
- In-memory only — a worker restart loses queued/running jobs. Completed
  results are durably saved to ``documents`` / ``scans`` tables, so users
  can always recover finished work via History.
- Single-process — assumes ``--workers 1`` in dev. For multi-worker
  production, swap this for Redis/Celery later.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.services import progress as scan_progress
from app.utils.logger import get_logger

logger = get_logger(__name__)


JobStatus = str  # "queued" | "running" | "completed" | "failed"


@dataclass
class Job:
    job_id: str
    document_id: str
    user_id: int | None
    kind: str  # "text" | "file" | "google_doc"
    label: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)


class JobManager:
    """Thread-unsafe (asyncio single-loop) job registry."""

    _MAX_PER_USER = 50
    _COMPLETED_TTL_S = 3600  # keep finished results for 1h before cleanup

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._user_jobs: dict[int, list[str]] = {}

    def submit(
        self,
        *,
        user_id: int | None,
        document_id: str,
        kind: str,
        label: str,
        coro_factory: Callable[[], Awaitable[dict[str, Any]]],
    ) -> Job:
        self._gc()
        job_id = uuid.uuid4().hex
        job = Job(
            job_id=job_id,
            document_id=document_id,
            user_id=user_id,
            kind=kind,
            label=label,
        )
        self._jobs[job_id] = job
        if user_id is not None:
            user_list = self._user_jobs.setdefault(user_id, [])
            user_list.append(job_id)
            # Trim oldest if over cap
            while len(user_list) > self._MAX_PER_USER:
                old_id = user_list.pop(0)
                self._jobs.pop(old_id, None)

        async def _runner() -> None:
            job.status = "running"
            job.started_at = time.time()
            try:
                result = await coro_factory()
                job.result = result
                job.status = "completed"
            except asyncio.CancelledError:
                job.status = "failed"
                job.error = "Job was cancelled."
                raise
            except Exception as exc:
                logger.exception("job_failed", job_id=job_id, error=str(exc))
                job.error = str(exc) or type(exc).__name__
                job.status = "failed"
                tracker = scan_progress.get(document_id)
                if tracker is not None:
                    tracker.emit("error", job.error, -1)
                    tracker.complete()
            finally:
                job.completed_at = time.time()

        job._task = asyncio.create_task(_runner())
        logger.info("job_submitted", job_id=job_id, user_id=user_id, kind=kind)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_for_user(self, user_id: int, *, limit: int = 20) -> list[Job]:
        ids = self._user_jobs.get(user_id, [])
        jobs = [self._jobs[i] for i in ids if i in self._jobs]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _gc(self) -> None:
        """Drop completed jobs older than _COMPLETED_TTL_S."""
        now = time.time()
        stale = [
            jid for jid, j in self._jobs.items()
            if j.status in ("completed", "failed")
            and j.completed_at is not None
            and (now - j.completed_at) > self._COMPLETED_TTL_S
        ]
        for jid in stale:
            job = self._jobs.pop(jid, None)
            if job and job.user_id is not None:
                lst = self._user_jobs.get(job.user_id, [])
                if jid in lst:
                    lst.remove(jid)


_manager: JobManager | None = None


def get_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
