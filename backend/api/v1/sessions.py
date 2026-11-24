"""Time-lapse session routes: list, detail, frames (paginated), rename, delete."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok, Page
from backend.api.schemas.sessions import (
    SessionDetail,
    SessionFrame,
    SessionManifest,
    SessionRename,
    SessionSummary,
)
from backend.core.security import require_api_key
from backend.services.sessions import SessionStore


def build_sessions_service(state: object) -> SessionStore:
    # crash recovery (recover_interrupted) runs in a thread at app startup (backend/app.py)
    return SessionStore(state.storage)  # type: ignore[attr-defined]


get_sessions = service_dep("sessions", build_sessions_service)
SessionsDep = Annotated[SessionStore, Depends(get_sessions)]

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def _detail(m: SessionManifest) -> SessionDetail:
    return SessionDetail(**SessionStore.summarize(m).model_dump(), config=m.config, videos=m.videos)


@router.get("", operation_id="list_sessions", response_model=Page[SessionSummary])
async def list_sessions(
    store: SessionsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[SessionSummary]:
    items = await store.list()
    s = (page - 1) * limit
    return Page[SessionSummary](
        items=items[s : s + limit], total=len(items), page=page, limit=limit
    )


@router.get("/{session_id}", operation_id="get_session", response_model=SessionDetail)
async def get_session(session_id: str, store: SessionsDep) -> SessionDetail:
    return _detail(await store.get(session_id))


@router.get(
    "/{session_id}/frames", operation_id="list_session_frames", response_model=Page[SessionFrame]
)
async def list_session_frames(
    session_id: str,
    store: SessionsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[SessionFrame]:
    m = await store.get(session_id)
    items = await store.list_frames(session_id, (page - 1) * limit, limit)
    return Page[SessionFrame](items=items, total=m.frames_captured, page=page, limit=limit)


@router.patch("/{session_id}", operation_id="rename_session", response_model=SessionDetail)
async def rename_session(session_id: str, body: SessionRename, store: SessionsDep) -> SessionDetail:
    return _detail(await store.update(session_id, name=body.name))


@router.delete("/{session_id}", operation_id="delete_session", response_model=Ok)
async def delete_session(session_id: str, store: SessionsDep) -> Ok:
    await store.delete(session_id)
    return Ok()
