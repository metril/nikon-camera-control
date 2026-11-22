"""Job schema (mirrors ``backend.core.jobs.Job``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.core.jobs import JobStatus


class JobOut(BaseModel):
    id: str
    kind: str
    status: JobStatus
    progress: float = Field(ge=0.0, le=1.0)
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    created: datetime
    started: datetime | None = None
    finished: datetime | None = None
