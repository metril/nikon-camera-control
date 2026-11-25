"""Job schema (mirrors ``backend.core.jobs.Job``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.core.jobs import JobStatus


class JobOut(BaseModel):
    id: str
    kind: str
    target: str | None = None
    status: JobStatus
    progress: float | None = Field(
        ge=0.0, le=1.0, description="0..1, or null while the total is unknown"
    )
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None
