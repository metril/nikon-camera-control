"""Kiosk routes: open event streams of the touchscreen display scale and on/off state."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import ConfigStoreDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.kiosk import KioskDisplayIn, KioskDisplayOut
from backend.core.config_store import AppConfig
from backend.core.security import require_api_key

router = APIRouter(tags=["kiosk"])

# Idle heartbeat period; a module constant so tests can shorten it.
PING_INTERVAL_S = 15.0


def _sse(
    request: Request, current: str, queue: asyncio.Queue[str], unsubscribe: Callable[[], None]
) -> StreamingResponse:
    """Event stream: the current value, then every queued change, with an idle ping."""

    async def events() -> AsyncIterator[str]:
        try:
            yield f"data: {current}\n\n"
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


class DisplayState:
    """In-memory kiosk display state (on at start) and its stream subscribers."""

    def __init__(self) -> None:
        self.on = True
        self.mode = "dim"
        self._queues: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]] = set()

    def text(self) -> str:
        """`on`, or `off <mode>` (black, dim or off: how the panel should sleep)."""
        return "on" if self.on else f"off {self.mode}"

    def set(self, on: bool) -> None:
        if on == self.on:
            return
        self.on = on
        self._push()

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        if not self.on:
            self._push()

    def _push(self) -> None:
        for loop, q in list(self._queues):
            loop.call_soon_threadsafe(q.put_nowait, self.text())

    def subscribe(self) -> tuple[asyncio.Queue[str], Callable[[], None]]:
        entry = (asyncio.get_running_loop(), asyncio.Queue[str]())
        self._queues.add(entry)
        return entry[1], lambda: self._queues.discard(entry)


def _display(request: Request) -> DisplayState:
    state = getattr(request.app.state, "kiosk_display", None)
    if state is None:
        state = request.app.state.kiosk_display = DisplayState()
    return state


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
    return _sse(request, store.config.kiosk.scale, queue, unsubscribe)


@router.get(
    "/kiosk/display",
    operation_id="stream_kiosk_display",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string", "format": "binary"}}},
            "description": "One `data: on` or `data: off <black|dim|off>` line per state",
        }
    },
)
async def stream_kiosk_display(request: Request, store: ConfigStoreDep) -> StreamingResponse:
    """Open, read-only stream of whether the kiosk screen should be on or off.

    Sends the current state on connect and on every change (`on`, or `off <mode>` with the
    sleep mode: black, dim or off), `off <mode>` again if the mode changes while asleep, and
    `on` whenever the sleep setting is set to 0 (never). Open like the scale stream.
    """
    state = _display(request)
    state.mode = store.config.kiosk.sleep_mode
    queue, unsubscribe_queue = state.subscribe()

    def on_change(new: AppConfig, old: AppConfig) -> None:
        state.set_mode(new.kiosk.sleep_mode)
        if new.kiosk.sleep_after_min != old.kiosk.sleep_after_min and not new.kiosk.sleep_after_min:
            state.set(True)

    unsubscribe_cfg = store.subscribe(on_change)

    def unsubscribe() -> None:
        unsubscribe_queue()
        unsubscribe_cfg()

    return _sse(request, state.text(), queue, unsubscribe)


@router.post(
    "/kiosk/display",
    operation_id="set_kiosk_display",
    response_model=KioskDisplayOut,
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)
async def set_kiosk_display(body: KioskDisplayIn, request: Request) -> KioskDisplayOut:
    """Record the kiosk screen state (the kiosk page sends off when idle, on at a touch)."""
    state = _display(request)
    state.set(body.on)
    return KioskDisplayOut(on=state.on)
