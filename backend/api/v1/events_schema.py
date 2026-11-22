"""Documentation-only route that puts the typed WebSocket event models into the OpenAPI spec."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.events import CameraStateData, CameraStateEvent, TypedEvent
from backend.core.security import require_api_key

router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("/schema", operation_id="get_event_schema", response_model=TypedEvent)
async def get_event_schema() -> TypedEvent:
    """No-op: returns a sample event. Its response model is the discriminated union of every
    event delivered on ``/ws/events`` (discriminator ``type``); it exists so the spec and the
    generated client carry the event types."""
    return CameraStateEvent(data=CameraStateData(state="idle", previous=None, connected=True))
