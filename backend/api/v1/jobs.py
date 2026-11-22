"""Background jobs: list, inspect, cancel."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import JobManagerDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.jobs import JobOut
from backend.core.jobs import JobStatus
from backend.core.security import require_api_key

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("", operation_id="list_jobs", response_model=list[JobOut])
async def list_jobs(
    jobs: JobManagerDep, kind: str | None = None, status: JobStatus | None = None
) -> list[JobOut]:
    return [JobOut.model_validate(j.model_dump()) for j in jobs.list(kind=kind, status=status)]


@router.get("/{job_id}", operation_id="get_job", response_model=JobOut)
async def get_job(job_id: str, jobs: JobManagerDep) -> JobOut:
    return JobOut.model_validate(jobs.get(job_id).model_dump())


@router.delete("/{job_id}", operation_id="cancel_job", response_model=JobOut)
async def cancel_job(job_id: str, jobs: JobManagerDep) -> JobOut:
    """Cancel a job (no-op for finished jobs) and return its final state."""
    return JobOut.model_validate((await jobs.cancel(job_id)).model_dump())
