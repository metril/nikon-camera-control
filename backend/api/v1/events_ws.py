"""WebSocket event stream: camera_state snapshot, then every bus event as JSON."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket

from backend.api.deps import ws_get_camera_service, ws_get_event_bus
from backend.api.schemas.common import Event, EventType
from backend.core.events import Subscription
from backend.core.security import AuthWatch, ws_authorize, ws_subprotocol

router = APIRouter(tags=["events"])

_CLOSE_TRY_AGAIN = 1013


@router.websocket("/ws/events")
async def events_ws(websocket: WebSocket) -> None:
    """Auth via the ``apikey.<key>`` subprotocol only (rejected: accept, then close 4401).

    Client may send ``{"type":"ping"}`` and gets ``{"type":"pong"}``."""
    if not await ws_authorize(websocket):
        return
    watch = AuthWatch(websocket)
    try:
        await websocket.accept(subprotocol=ws_subprotocol(websocket))
    except BaseException:
        watch.close()  # the handler's finally is not reached yet
        raise
    sub = ws_get_event_bus(websocket).subscribe()  # before the snapshot: no gap
    send_lock = asyncio.Lock()

    async def send(text: str) -> None:
        async with send_lock:
            await websocket.send_text(text)

    async def writer(sub: Subscription) -> None:
        st = ws_get_camera_service(websocket).status()
        snapshot = Event(
            type=EventType.CAMERA_STATE,
            data={"state": st.state.value, "previous": None, "connected": st.connected},
        )
        await send(snapshot.model_dump_json())
        async for event in sub:
            await send(event.model_dump_json())
        # iterator ended: slow subscriber dropped, or the bus closed
        async with send_lock:
            await websocket.close(code=_CLOSE_TRY_AGAIN if sub.dropped else 1001)

    async def reader() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await send(json.dumps({"type": "pong"}))

    async def key_guard() -> None:
        await watch.changed.wait()
        async with send_lock:
            await websocket.close(code=4401, reason="API key changed")

    tasks = [
        asyncio.create_task(writer(sub)),
        asyncio.create_task(reader()),
        asyncio.create_task(key_guard()),
    ]
    for t in tasks:
        t.add_done_callback(_consume)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass  # server/test-client teardown cancels the handler; this is its end of life anyway
    finally:
        # synchronous cleanup: awaits here could be cancelled again by the teardown scope
        sub.close()
        watch.close()
        for t in tasks:
            t.cancel()


def _consume(task: asyncio.Task[None]) -> None:
    """Retrieve the outcome so a send on a gone client is not logged as never-retrieved."""
    if not task.cancelled():
        task.exception()
