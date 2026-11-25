"""JobManager: background asyncio jobs with status, progress and cancellation."""

from __future__ import annotations

import asyncio
import builtins
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.api.schemas.common import EventType
from backend.core.errors import AppError, CameraBusy, JobNotFound
from backend.core.events import EventBus

log = logging.getLogger(__name__)

_PROGRESS_INTERVAL = 0.2  # seconds; ~5 progress events/s per job
CANCEL_WAIT_S = 10.0  # default bound for cancel() / shutdown() awaiting job cleanup


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
    target: str | None = None  # what the job works on (e.g. a storage location id)
    status: JobStatus = JobStatus.QUEUED
    progress: float | None = Field(
        default=0.0, ge=0.0, le=1.0, description="0..1, or null while the total is unknown"
    )
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
        self._partial_result: dict[str, Any] | None = None
        self._last_emit = float("-inf")

    @property
    def job_id(self) -> str:
        return self._job.id

    def set_partial_result(self, result: dict[str, Any]) -> None:
        """Result kept on the job if it ends cancelled or failed (what was done so far)."""
        self._partial_result = result

    def report(self, progress: float | None, message: str = "") -> None:
        """Update progress (clamped to 0..1; None = total unknown) and publish JOB_PROGRESS
        (throttled)."""
        if progress is not None:
            progress = min(1.0, max(0.0, progress))
        self._job.progress = progress
        if message:
            self._job.message = message
        now = self._manager._clock()
        if (progress is None or progress < 1.0) and now - self._last_emit < _PROGRESS_INTERVAL:
            return
        self._last_emit = now
        self._manager._publish(EventType.JOB_PROGRESS, self._job)

    @property
    def cancelled(self) -> bool:
        """True once cancel() was requested (cooperative check for long sync loops)."""
        return self._cancel_requested


class HeldContext:
    """An async context manager (e.g. ``CameraService.lease``) entered by one coroutine and
    exited, once, by another (the job). ``release`` is idempotent."""

    def __init__(self, cm: AbstractAsyncContextManager[Any]) -> None:
        self._cm = cm
        self._entered = False

    async def enter(self) -> None:
        await self._cm.__aenter__()
        self._entered = True

    async def release(self) -> None:
        if self._entered:
            self._entered = False
            await self._cm.__aexit__(None, None, None)


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
    - ``cancel`` / ``shutdown`` wait at most ``wait_s`` for the task's cleanup. A task that
      has not finished by then is reported ``cancelled`` ("cancelling" message), keeps
      cleaning up in the background and is logged loudly; it is never awaited forever.
    - ``release`` (submit): async hook run only if the job is cancelled before its task ever
      started (the factory's own ``finally`` cannot run then), e.g. to free a lease.
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
        self._releases: dict[str, Callable[[], Awaitable[None]]] = {}
        self._lingering: set[asyncio.Task[None]] = set()
        self._finished: deque[str] = deque()

    def _publish(self, type: EventType, job: Job) -> None:
        self._bus.publish(type, {"job": job.model_dump(mode="json")})

    def submit(
        self,
        kind: str,
        coro_factory: JobFactory,
        *,
        exclusive_key: str | None = None,
        release: Callable[[], Awaitable[None]] | None = None,
        target: str | None = None,
    ) -> Job:
        if exclusive_key is not None and exclusive_key in self._keys:
            raise CameraBusy(
                f"A '{kind}' job is already running for this target",
                details={"exclusive_key": exclusive_key, "job_id": self._keys[exclusive_key]},
            )
        job = Job(id=uuid.uuid4().hex, kind=kind, target=target, created=datetime.now(UTC))
        ctx = JobContext(self, job)
        self._jobs[job.id] = job
        self._ctxs[job.id] = ctx
        if exclusive_key is not None:
            self._keys[exclusive_key] = job.id
            self._job_keys[job.id] = exclusive_key
        if release is not None:
            self._releases[job.id] = release
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
            if ctx._partial_result is not None and job.status not in _FINISHED:
                job.result = ctx._partial_result
            self._finish(job, JobStatus.CANCELLED, EventType.JOB_CANCELLED)
        except AppError as exc:
            if job.status not in _FINISHED:
                job.error, job.error_code = exc.message, str(exc.code)
            self._finish(job, JobStatus.FAILED, EventType.JOB_FAILED)
        except Exception as exc:
            log.exception("job %s (%s) failed", job.id, job.kind)
            if job.status not in _FINISHED:
                job.error = str(exc) or type(exc).__name__
            self._finish(job, JobStatus.FAILED, EventType.JOB_FAILED)
        else:
            if job.status not in _FINISHED:  # not already reported cancelled
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
        self._releases.pop(job.id, None)
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

    async def cancel(self, job_id: str, *, wait_s: float = CANCEL_WAIT_S) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(details={"job_id": job_id})
        if job.status in _FINISHED:
            return job.model_copy()
        await self._cancel_jobs([job], wait_s)
        return job.model_copy()

    async def _cancel_jobs(self, jobs: builtins.list[Job], wait_s: float) -> None:
        tasks: dict[str, asyncio.Task[None]] = {}
        unstarted: builtins.list[Job] = []
        for job in jobs:
            ctx = self._ctxs.get(job.id)
            task = self._tasks.get(job.id)
            if ctx is not None:
                ctx._cancel_requested = True
            if task is not None:
                if job.status == JobStatus.QUEUED:
                    unstarted.append(job)  # the factory will never run its own cleanup
                task.cancel()
                tasks[job.id] = task
        if tasks:
            _, pending = await asyncio.wait(set(tasks.values()), timeout=wait_s)
            for job in jobs:
                task = tasks.get(job.id)
                if task is not None and task in pending:
                    log.error(
                        "job %s (%s) did not finish %.1fs after cancel; reporting it cancelled "
                        "while its cleanup continues in the background",
                        job.id,
                        job.kind,
                        wait_s,
                    )
                    job.message = "cancelling: cleanup still running"
                    self._lingering.add(task)
                    task.add_done_callback(self._lingering.discard)
        for job in unstarted:
            release = self._releases.get(job.id)
            if release is not None:
                try:
                    await release()
                except Exception:
                    log.exception("releasing resources of unstarted job %s failed", job.id)
        for job in jobs:
            # a task cancelled before its first step never ran its handler
            self._finish(job, JobStatus.CANCELLED, EventType.JOB_CANCELLED)

    async def shutdown(self, *, wait_s: float = CANCEL_WAIT_S) -> None:
        await self._cancel_jobs(
            [j for j in self._jobs.values() if j.status not in _FINISHED], wait_s
        )
        for task in self._lingering:
            log.error("task %s is still running after job shutdown", task.get_name())
