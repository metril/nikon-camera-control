"""JobManager: background asyncio jobs with status, progress and cancellation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.core.events import EventBus


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(BaseModel):
    id: str
    kind: str  # e.g. "video", "download_all", "focus_stack"
    status: JobStatus = JobStatus.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None


class JobContext:
    """Handed to the job coroutine."""

    @property
    def job_id(self) -> str:
        raise NotImplementedError

    def report(self, progress: float, message: str = "") -> None:
        """Update progress (clamped to 0..1) and publish JOB_PROGRESS. Sync, non-blocking."""
        raise NotImplementedError

    @property
    def cancelled(self) -> bool:
        """True once cancel() was requested (cooperative check for long sync loops)."""
        raise NotImplementedError


JobFactory = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobManager:
    """Contract:
    - ``submit`` creates the Job (QUEUED), publishes JOB_CREATED, schedules an asyncio
      task, and returns the Job snapshot immediately. Must run on the event loop.
    - The task sets RUNNING, awaits the factory's coroutine, then COMPLETED (result =
      returned dict) / FAILED (error = str(exc); AppError message kept) / CANCELLED, each
      publishing JOB_COMPLETED / JOB_FAILED / JOB_CANCELLED. Exceptions never leak.
    - ``cancel`` cancels the task (CancelledError inside the coroutine) and returns the
      updated Job; cancelling a finished job returns it unchanged. Raises JobNotFound.
    - ``get`` raises JobNotFound. ``list`` is newest first, optional status/kind filter.
    - Finished jobs are retained (bounded, oldest evicted, ``max_finished`` default 200).
    - ``shutdown`` cancels all running jobs and awaits them.
    """

    def __init__(self, event_bus: EventBus, *, max_finished: int = 200) -> None:
        raise NotImplementedError

    def submit(self, kind: str, coro_factory: JobFactory) -> Job:
        raise NotImplementedError

    def get(self, job_id: str) -> Job:
        raise NotImplementedError

    def list(self, *, status: JobStatus | None = None, kind: str | None = None) -> list[Job]:
        raise NotImplementedError

    async def cancel(self, job_id: str) -> Job:
        raise NotImplementedError

    async def shutdown(self) -> None:
        raise NotImplementedError
