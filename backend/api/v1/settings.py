"""Camera settings routes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.settings import (
    RangeOut,
    SettingOut,
    SettingsPatchIn,
    SettingsPatchOut,
    SettingValueIn,
)
from backend.core.security import require_api_key
from backend.services.settings import SettingsService, SettingView

get_settings_service = service_dep("settings", lambda s: SettingsService(s.camera_service))
SettingsDep = Annotated[SettingsService, Depends(get_settings_service)]

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def _out(v: SettingView) -> SettingOut:
    return SettingOut(
        name=v.name,
        alias=v.alias,
        label=v.label,
        path=v.path,
        type=v.type,
        value=v.value,
        readonly=v.readonly,
        choices=list(v.choices),
        range=RangeOut(min=v.range.min, max=v.range.max, step=v.range.step) if v.range else None,
        writable=v.writable,
    )


@router.get("", operation_id="list_settings", response_model=list[SettingOut])
async def list_settings(
    svc: SettingsDep, group: Annotated[Literal["common", "all"], Query()] = "common"
) -> list[SettingOut]:
    return [_out(v) for v in await svc.list_settings(group)]


@router.patch("", operation_id="update_settings", response_model=SettingsPatchOut)
async def update_settings(body: SettingsPatchIn, svc: SettingsDep) -> SettingsPatchOut:
    res = await svc.set_many(body.values)
    return SettingsPatchOut(results=[_out(v) for v in res.applied])


@router.get("/{name}", operation_id="get_setting", response_model=SettingOut)
async def get_setting(name: str, svc: SettingsDep) -> SettingOut:
    return _out(await svc.get(name))


@router.put("/{name}", operation_id="set_setting", response_model=SettingOut)
async def set_setting(name: str, body: SettingValueIn, svc: SettingsDep) -> SettingOut:
    return _out(await svc.set(name, body.value))
