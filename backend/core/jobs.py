"""JobManager: background asyncio jobs with status, progress and cancellation."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.api.schemas.common import EventType
from backend.core.errors import AppError, CameraBusy, JobNotFound
from backend.core.events import EventBus

log = logging.getLogger(__name__)

_PROGRESS_INTERVAL = 0.2  # seconds; ~5 progress events/s per job


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_FINISHED = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


class Job(BaseModel):
    id: str
    kind: str  # e.g. "video", "download_all", "focus_stack"
    status: JobStatus = JobStatus.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None  # AppError.code when the failure was an AppError
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None


class JobContext:
    """Handed to the job coroutine."""

    def __init__(self, manager: JobManager, job: Job) -> None:
        self._manager = manager
        self._job = job
        self._cancel_requested = False
        self._last_emit = float("-inf")

    @property
    def job_id(self) -> str:
        return self._job.id

    def report(self, progress: float, message: str = "") -> None:
        """Update progress (clamped to 0..1) and publish JOB_PROGRESS (throttled)."""
        progress = min(1.0, max(0.0, progress))
        self._job.progress = progress
        if message:
            self._job.message = message
        now = self._manager._clock()
        if progress < 1.0 and now - self._last_emit < _PROGRESS_INTERVAL:
            return
        self._last_emit = now
        self._manager._publish(EventType.JOB_PROGRESS, self._job)

    @property
    def cancelled(self) -> bool:
        """True once cancel() was requested (cooperative check for long sync loops)."""
        return self._cancel_requested


JobFactory = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobManager:
    """Background asyncio jobs with status, progress and cancellation.

    - ``submit`` (event loop only) creates a QUEUED Job, publishes JOB_CREATED, schedules
      a task and returns the snapshot. The task goes RUNNING then COMPLETED / FAILED /
      CANCELLED, publishing JOB_COMPLETED / JOB_FAILED / JOB_CANCELLED. Exceptions never
      leak. On failure ``error`` is the message and ``error_code`` the AppError code.
    - ``exclusive_key``: while a job with that key is unfinished, submitting another with
      the same key raises CameraBusy (HTTP 409).
    - ``cancel`` returns the updated Job; cancelling a finished job is a no-op.
    - Only the newest ``max_finished`` finished jobs are retained.
    - ``shutdown`` cancels and awaits all unfinished jobs.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        max_finished: int = 100,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = event_bus
        self._max_finished = max_finished
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._ctxs: dict[str, JobContext] = {}
        self._keys: dict[str, str] = {}  # exclusive_key -> job id
        self._job_keys: dict[str, str] = {}  # job id -> exclusive_key
        self._finished: deque[str] = deque()

    def _publish(self, type: EventType, job: Job) -> None:
        self._bus.publish(type, {"job": job.model_dump(mode="json")})

    def submit(
        self, kind: str, coro_factory: JobFactory, *, exclusive_key: str | None = None
    ) -> Job:
        if exclusive_key is not None and exclusive_key in self._keys:
            raise CameraBusy(
                f"A '{kind}' job is already running for this target",
                details={"exclusive_key": exclusive_key, "job_id": self._keys[exclusive_key]},
            )
        job = Job(id=uuid.uuid4().hex, kind=kind, created=datetime.now(UTC))
        ctx = JobContext(self, job)
        self._jobs[job.id] = job
        self._ctxs[job.id] = ctx
        if exclusive_key is not None:
            self._keys[exclusive_key] = job.id
            self._job_keys[job.id] = exclusive_key
        self._tasks[job.id] = asyncio.get_running_loop().create_task(
            self._run(job, ctx, coro_factory)
        )
        self._publish(EventType.JOB_CREATED, job)
        return job.model_copy()

    async def _run(self, job: Job, ctx: JobContext, factory: JobFactory) -> None:
        try:
            job.status = JobStatus.RUNNING
            job.started = datetime.now(UTC)
            result = await factory(ctx)
        except asyncio.CancelledError:
            self._finish(job, JobStatus.CANCELLED, EventType.JOB_CANCELLED)
        except AppError as exc:
            job.error, job.error_code = exc.message, str(exc.code)
            self._finish(job, JobStatus.FAILED, EventType.JOB_FAILED)
        except Exception as exc:
            log.exception("job %s (%s) failed", job.id, job.kind)
            job.error = str(exc) or type(exc).__name__
            self._finish(job, JobStatus.FAILED, EventType.JOB_FAILED)
        else:
            job.result = result
            job.progress = 1.0
            self._finish(job, JobStatus.COMPLETED, EventType.JOB_COMPLETED)

    def _finish(self, job: Job, status: JobStatus, event: EventType) -> None:
        if job.status in _FINISHED:
            return
        job.status = status
        job.finished = datetime.now(UTC)
        self._tasks.pop(job.id, None)
        self._ctxs.pop(job.id, None)
        key = self._job_keys.pop(job.id, None)
        if key is not None:
            self._keys.pop(key, None)
        self._finished.append(job.id)
        while len(self._finished) > self._max_finished:
            self._jobs.pop(self._finished.popleft(), None)
        self._publish(event, job)

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id].model_copy()
        except KeyError:
            raise JobNotFound(details={"job_id": job_id}) from None

    def list(self, *, status: JobStatus | None = None, kind: str | None = None) -> list[Job]:
        jobs = [
            j.model_copy()
            for j in self._jobs.values()
            if (status is None or j.status == status) and (kind is None or j.kind == kind)
        ]
        jobs.sort(key=lambda j: j.created, reverse=True)
        return jobs

    async def cancel(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(details={"job_id": job_id})
        if job.status in _FINISHED:
            return job.model_copy()
        await self._cancel_task(job)
        return job.model_copy()

    async def _cancel_task(self, job: Job) -> None:
        ctx = self._ctxs.get(job.id)
        task = self._tasks.get(job.id)
        if ctx is not None:
            ctx._cancel_requested = True
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # task cancelled before its first step never ran its handler
        self._finish(job, JobStatus.CANCELLED, EventType.JOB_CANCELLED)

    async def shutdown(self) -> None:
        for job in [j for j in self._jobs.values() if j.status not in _FINISHED]:
            await self._cancel_task(job)
