"""Live view routes: start/stop, status, snapshot and the binary frame WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response, WebSocket

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.files import binary_response
from backend.api.schemas.liveview import LiveViewStatusOut
from backend.core.security import KeyWatch, require_api_key, ws_authorize, ws_subprotocol
from backend.services.liveview import LiveViewService, Subscriber

get_liveview = service_dep(
    "liveview", lambda s: LiveViewService(s.camera_service, s.event_bus, s.config_store)
)
LiveViewDep = Annotated[LiveViewService, Depends(get_liveview)]

router = APIRouter(
    prefix="/liveview",
    tags=["liveview"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)
ws_router = APIRouter(tags=["liveview"])


def _status(svc: LiveViewService, sub: Subscriber | None = None) -> LiveViewStatusOut:
    st = svc.stats()
    out = LiveViewStatusOut(
        running=st.running,
        active=st.active,
        sticky=st.sticky,
        phase=st.phase,
        reason=st.reason,
        camera_state=st.camera_state,
        fps=st.fps,
        target_fps=st.target_fps,
        subscribers=st.subscribers,
        frames_produced=st.frames_produced,
        frames_sent=st.frames_sent,
        frames_dropped=st.frames_dropped,
        last_frame_bytes=st.last_frame_bytes,
        last_frame_at=st.last_frame_at,
    )
    if sub is not None:
        out.client_frames_sent = sub.frames_sent
        out.client_frames_dropped = sub.frames_dropped
    return out


@router.get("", operation_id="get_liveview", response_model=LiveViewStatusOut)
async def get_liveview_status(svc: LiveViewDep) -> LiveViewStatusOut:
    return _status(svc)


@router.post("/start", operation_id="start_liveview", response_model=LiveViewStatusOut)
async def start_liveview(svc: LiveViewDep) -> LiveViewStatusOut:
    """Start the stream and keep it running until stopped, even with no clients."""
    await svc.start()
    return _status(svc)


@router.post("/stop", operation_id="stop_liveview", response_model=LiveViewStatusOut)
async def stop_liveview(svc: LiveViewDep) -> LiveViewStatusOut:
    await svc.stop()
    return _status(svc)


@router.get(
    "/snapshot",
    operation_id="get_liveview_snapshot",
    response_class=Response,
    responses=binary_response("image/jpeg", "One live view JPEG"),
)
async def get_liveview_snapshot(svc: LiveViewDep) -> Response:
    return Response(content=await svc.snapshot(), media_type="image/jpeg")


@ws_router.websocket("/ws/liveview")
async def liveview_ws(websocket: WebSocket) -> None:
    """Binary JPEG frames plus JSON control. Auth via the ``apikey.<key>`` subprotocol.

    Client: ``{"type":"ping"}`` -> pong, ``{"type":"status"}`` -> status. Server: status on
    connect and whenever the stream changes state. Stays open while the camera is away."""
    if not await ws_authorize(websocket):
        return
    watch = KeyWatch(websocket)
    try:
        await websocket.accept(subprotocol=ws_subprotocol(websocket))
    except BaseException:
        watch.close()  # the handler's finally is not reached yet
        raise
    svc = get_liveview(websocket)
    sub = svc.subscribe()
    send_lock = asyncio.Lock()

    async def send_status() -> None:
        text = json.dumps({"type": "status", **_status(svc, sub).model_dump(mode="json")})
        async with send_lock:
            await websocket.send_text(text)

    async def writer() -> None:
        while (item := await sub.get()) is not None:
            kind, frame = item
            if kind == "status":
                await send_status()
            elif frame is not None:
                async with send_lock:
                    await websocket.send_bytes(frame)
        async with send_lock:
            await websocket.close(code=1001)

    async def reader() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind == "ping":
                async with send_lock:
                    await websocket.send_text(json.dumps({"type": "pong"}))
            elif kind == "status":
                await send_status()

    async def key_guard() -> None:
        await watch.changed.wait()
        async with send_lock:
            await websocket.close(code=4401, reason="API key changed")

    tasks = [
        asyncio.create_task(writer()),
        asyncio.create_task(reader()),
        asyncio.create_task(key_guard()),
    ]
    for t in tasks:
        t.add_done_callback(_consume)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass  # server/test-client teardown cancels the handler
    finally:
        svc.unsubscribe(sub)  # synchronous: awaits here could be cancelled again
        watch.close()
        for t in tasks:
            t.cancel()


def _consume(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
