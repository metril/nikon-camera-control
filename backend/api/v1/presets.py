"""Preset routes: named camera-setting sets and bracket sets, persisted across restarts."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok
from backend.api.schemas.presets import (
    ID_PATTERN,
    ApplyResult,
    FromCameraIn,
    PresetCollection,
    PresetExport,
    PresetImportIn,
    PresetImportResult,
    PresetIn,
    PresetItem,
)
from backend.core.security import require_api_key
from backend.services.presets import PresetService
from backend.services.settings import SettingsService

get_presets = service_dep(
    "presets",
    lambda s: PresetService(s.data_dir, SettingsService(s.camera_service), bus=s.event_bus),
)
Svc = Annotated[PresetService, Depends(get_presets)]
PresetId = Annotated[str, Path(pattern=ID_PATTERN, description="Preset id.")]

router = APIRouter(
    prefix="/presets",
    tags=["presets"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("", operation_id="list_presets", response_model=PresetCollection)
async def list_presets(
    svc: Svc, kind: Annotated[Literal["settings", "bracket"] | None, Query()] = None
) -> PresetCollection:
    """User presets plus the read-only built-in bracket presets (`builtin: true`)."""
    return await svc.list(kind)


@router.post("", operation_id="create_preset", response_model=PresetItem, status_code=201)
async def create_preset(body: PresetIn, svc: Svc) -> PresetItem:
    """Create a preset. Names are unique per kind (case-insensitive), 1-80 characters."""
    return PresetItem(await svc.create(body))


@router.get("/export", operation_id="export_presets", response_model=PresetExport)
async def export_presets(svc: Svc) -> PresetExport:
    """All user presets as a JSON document (built-ins excluded) for backup or transfer."""
    return await svc.export()


@router.post("/import", operation_id="import_presets", response_model=PresetImportResult)
async def import_presets(body: PresetImportIn, svc: Svc) -> PresetImportResult:
    """Validate and import presets from an export; every item gets its own result.
    `replace=true` swaps the whole user set for the valid items."""
    return await svc.import_(body)


@router.post(
    "/from-camera",
    operation_id="create_preset_from_camera",
    response_model=PresetItem,
    status_code=201,
)
async def create_preset_from_camera(body: FromCameraIn, svc: Svc) -> PresetItem:
    """Snapshot the camera's current values into a new settings preset (default: the common
    writable settings)."""
    return PresetItem(await svc.from_camera(body))


@router.get("/{preset_id}", operation_id="get_preset", response_model=PresetItem)
async def get_preset(preset_id: PresetId, svc: Svc) -> PresetItem:
    return PresetItem(await svc.get(preset_id))


@router.put("/{preset_id}", operation_id="update_preset", response_model=PresetItem)
async def update_preset(preset_id: PresetId, body: PresetIn, svc: Svc) -> PresetItem:
    """Replace a user preset (same kind). Built-ins answer 403."""
    return PresetItem(await svc.update(preset_id, body))


@router.delete("/{preset_id}", operation_id="delete_preset", response_model=Ok)
async def delete_preset(preset_id: PresetId, svc: Svc) -> Ok:
    """Delete a user preset. Built-ins answer 403."""
    await svc.delete(preset_id)
    return Ok()


@router.post("/{preset_id}/apply", operation_id="apply_preset", response_model=ApplyResult)
async def apply_preset(preset_id: PresetId, svc: Svc) -> ApplyResult:
    """Settings preset: validate every value against the connected camera (all or nothing),
    then apply and return what the camera now reports. Bracket preset: nothing is started; the
    resolved steps are returned, and the UI then passes the preset's `bracketing` object to the
    time-lapse config or one-shot bracket endpoint."""
    return await svc.apply(preset_id)
