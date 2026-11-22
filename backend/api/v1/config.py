"""Config routes: read/patch/reset options and manage the API key."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from backend.api.deps import ConfigStoreDep, EventBusDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import EventType
from backend.api.schemas.config import (
    ApiKeyDeletedOut,
    ApiKeyOut,
    ConfigOut,
    ConfigSchemaOut,
    ConfigUpdateOut,
)
from backend.core.config_store import AppConfig
from backend.core.security import generate_api_key, hash_api_key, require_api_key

# No key configured -> require_api_key is a no-op (first-time setup from the UI).
router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def _out(cfg: AppConfig) -> ConfigOut:
    return ConfigOut.model_validate(cfg.public_dump())


def _changed(bus: EventBusDep, cfg: AppConfig, restart: list[str]) -> None:
    bus.publish(
        EventType.CONFIG_CHANGED, {"config": cfg.public_dump(), "restart_required": restart}
    )


@router.get("", operation_id="get_config", response_model=ConfigOut)
async def get_config(store: ConfigStoreDep) -> ConfigOut:
    return _out(store.config)


@router.get("/schema", operation_id="get_config_schema", response_model=ConfigSchemaOut)
async def get_config_schema(store: ConfigStoreDep) -> ConfigSchemaOut:
    return ConfigSchemaOut(json_schema=store.public_schema())


@router.patch("", operation_id="update_config", response_model=ConfigUpdateOut)
async def update_config(
    store: ConfigStoreDep,
    bus: EventBusDep,
    patch: Annotated[dict[str, Any], Body(title="ConfigPatch")],
) -> ConfigUpdateOut:
    new, restart = store.update(patch)
    _changed(bus, new, restart)
    return ConfigUpdateOut(config=_out(new), restart_required=restart)


@router.post("/reset", operation_id="reset_config", response_model=ConfigUpdateOut)
async def reset_config(store: ConfigStoreDep, bus: EventBusDep) -> ConfigUpdateOut:
    new = store.reset()
    _changed(bus, new, [])
    return ConfigUpdateOut(config=_out(new), restart_required=[])


@router.post("/api-key", operation_id="create_api_key", response_model=ApiKeyOut)
async def create_api_key(store: ConfigStoreDep, bus: EventBusDep) -> ApiKeyOut:
    """Generate (or rotate) the API key. The plaintext key is returned only here."""
    key = generate_api_key()
    new = store.set_api_key_hash(hash_api_key(key))
    _changed(bus, new, [])
    return ApiKeyOut(api_key=key, config=_out(new))


@router.delete("/api-key", operation_id="delete_api_key", response_model=ApiKeyDeletedOut)
async def delete_api_key(store: ConfigStoreDep, bus: EventBusDep) -> ApiKeyDeletedOut:
    new = store.set_api_key_hash(None)
    _changed(bus, new, [])
    return ApiKeyDeletedOut(config=_out(new))
