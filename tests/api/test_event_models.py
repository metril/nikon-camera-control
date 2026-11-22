"""Every typed event model matches what the real services publish."""

import asyncio
import time
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import TypeAdapter

from backend.api.schemas.common import EventType
from backend.api.schemas.events import EVENT_MODELS, TypedEvent
from backend.services.timelapse import runner as runner_mod

ADAPTER: TypeAdapter[Any] = TypeAdapter(TypedEvent)


async def _drain(sub: Any) -> list[Any]:
    out = []
    await asyncio.sleep(0.05)
    while True:
        try:
            out.append(await asyncio.wait_for(sub.__anext__(), 0.1))
        except TimeoutError:
            return out


def test_every_event_type_has_a_model() -> None:
    assert set(EVENT_MODELS) == set(EventType)


async def test_spec_carries_event_types(app: FastAPI) -> None:
    spec = app.openapi()
    op = spec["paths"]["/api/v1/events/schema"]["get"]
    assert op["operationId"] == "get_event_schema"
    assert {"TimelapseFrameEvent", "JobCompletedEvent", "ConfigChangedEvent"} <= set(
        spec["components"]["schemas"]
    )


async def test_published_payloads_validate(
    app: FastAPI, connected_client: httpx.AsyncClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0.0)
    c = connected_client
    seen: dict[str, Any] = {}
    async with app.state.event_bus.subscribe() as sub:
        await c.put("/api/v1/settings/iso", json={"value": "200"})
        await c.post("/api/v1/capture", json={})
        await c.post("/api/v1/liveview/start")
        await c.post("/api/v1/liveview/stop")
        await c.post("/api/v1/recording/start", json={"max_seconds": 30})
        await c.post("/api/v1/recording/stop")
        await c.post(
            "/api/v1/presets", json={"kind": "settings", "name": "ev", "values": {"iso": "200"}}
        )
        await c.patch("/api/v1/config", json={"timelapse": {"failure_budget": 4}})
        body = {"name": "Ev", "interval_s": 0.2, "total_frames": 2}
        await c.put("/api/v1/timelapse/config", json=body)
        await c.post("/api/v1/timelapse/start")
        deadline = time.monotonic() + 10
        while (await c.get("/api/v1/timelapse")).json()["state"] not in {"completed", "failed"}:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        job = (await c.post("/api/v1/camera/files/download-all", json={})).json()
        while (await c.get(f"/api/v1/jobs/{job['id']}")).json()["status"] in {"queued", "running"}:  # noqa: ASYNC110
            await asyncio.sleep(0.02)
        await c.post("/api/v1/camera/disconnect")
        for ev in await _drain(sub):
            model = ADAPTER.validate_python(ev.model_dump(mode="json"))
            assert model.type == ev.type
            seen[ev.type.value] = model
    expected = {
        "camera_state",
        "setting_changed",
        "capture_started",
        "capture_complete",
        "liveview_started",
        "liveview_stopped",
        "recording_started",
        "recording_stopped",
        "presets_changed",
        "config_changed",
        "timelapse_started",
        "timelapse_frame",
        "timelapse_completed",
        "job_created",
        "job_completed",
        "camera_disconnected",
    }
    assert expected <= set(seen), expected - set(seen)
