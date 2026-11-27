"""Kiosk routes: an open event stream of the touchscreen display scale."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import ConfigStoreDep
from backend.core.config_store import AppConfig

router = APIRouter(tags=["kiosk"])

# Idle heartbeat period; a module constant so tests can shorten it.
PING_INTERVAL_S = 15.0


@router.get(
    "/kiosk/scale",
    operation_id="stream_kiosk_scale",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string", "format": "binary"}}},
            "description": "One `data: <scale>` line per value",
        }
    },
)
async def stream_kiosk_scale(request: Request, store: ConfigStoreDep) -> StreamingResponse:
    """Open, read-only stream of the kiosk display scale (auto, 1, 1.25, 1.5 or 2).

    Sends the current value on connect and again whenever it changes. Not sensitive, and the
    kiosk holds no API key, so it is open like /health.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def on_change(new: AppConfig, old: AppConfig) -> None:
        if new.kiosk.scale != old.kiosk.scale:
            loop.call_soon_threadsafe(queue.put_nowait, new.kiosk.scale)

    unsubscribe = store.subscribe(on_change)

    async def events() -> AsyncIterator[str]:
        try:
            yield f"data: {store.config.kiosk.scale}\n\n"
            while not await request.is_disconnected():
                try:
                    value = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {value}\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
