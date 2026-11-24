"""Focus routes: autofocus, manual drive, tracked position and focus stacking."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.focus import (
    AfPointRequest,
    AfPointResult,
    AutofocusResult,
    FocusRange,
    FocusResetResult,
    FocusStatus,
    MfRequest,
    MfResult,
    StackRequest,
)
from backend.api.schemas.jobs import JobOut
from backend.api.v1.capture import build_capture_service
from backend.core.security import require_api_key
from backend.services.focus import FocusService


def build_focus_service(s: State) -> FocusService:
    capture = s.services.get("capture", lambda: build_capture_service(s))
    return FocusService(
        s.camera_service,
        capture,
        s.job_manager,
        s.storage,
        default_prefix=lambda: s.config_store.config.camera.filename_prefix,
    )


get_focus = service_dep("focus", build_focus_service)
FocusDep = Annotated[FocusService, Depends(get_focus)]

router = APIRouter(
    prefix="/focus",
    tags=["focus"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("", operation_id="get_focus", response_model=FocusStatus)
async def get_focus_status(svc: FocusDep) -> FocusStatus:
    lo, hi, step = await svc.get_range()
    return FocusStatus(
        relative_position=svc.relative_position,
        range=FocusRange(min=lo, max=hi, step=step),
        last_af_at=svc.last_af_at,
    )


@router.post("/af", operation_id="autofocus", response_model=AutofocusResult)
async def autofocus(svc: FocusDep) -> AutofocusResult:
    return AutofocusResult(focused=await svc.autofocus())


@router.post("/point", operation_id="set_af_point", response_model=AfPointResult)
async def set_af_point(body: AfPointRequest, svc: FocusDep) -> AfPointResult:
    """Move the camera's AF point (``changeafarea``) to a normalized live view position."""
    x, y = await svc.set_af_point(body.x, body.y)
    return AfPointResult(x=x, y=y)


@router.post("/mf", operation_id="manual_focus", response_model=MfResult)
async def manual_focus(body: MfRequest, svc: FocusDep) -> MfResult:
    pos = await svc.move(body.steps)
    return MfResult(steps=body.steps, relative_position=pos)


@router.post("/reset", operation_id="reset_focus_position", response_model=FocusResetResult)
async def reset_focus_position(svc: FocusDep) -> FocusResetResult:
    return FocusResetResult(relative_position=svc.reset())


@router.post("/stack", operation_id="start_focus_stack", response_model=JobOut, status_code=202)
async def start_focus_stack(body: StackRequest, svc: FocusDep) -> JobOut:
    """Capture N shots, moving focus between them; returns the job (kind ``focus-stack``)."""
    job = await svc.start_stack(**body.model_dump())
    return JobOut.model_validate(job.model_dump())
