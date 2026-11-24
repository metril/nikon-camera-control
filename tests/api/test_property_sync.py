"""Settings changed on the camera body show up as SETTING_CHANGED (PTP property events)."""

import asyncio

import pytest
from fastapi import FastAPI

from backend.api.schemas.common import EventType
from backend.camera.backend import parse_property_change, parse_property_event
from backend.camera.fake import FakeCamera
from backend.core import camera_service, property_sync


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(camera_service, "_EVENT_POLL_S", 0.03)
    monkeypatch.setattr(property_sync, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(property_sync, "MIN_GAP_S", 0.2)
    monkeypatch.setattr(property_sync, "ECHO_S", 0.6)


async def _changes(app: FastAPI, name: str, action, wait_s: float = 0.5) -> list[object]:
    bus = app.state.event_bus
    seen: list[object] = []
    sub = bus.subscribe()

    async def collect() -> None:
        async for ev in sub:
            if ev.type == EventType.SETTING_CHANGED and ev.data["name"] == name:
                seen.append(ev.data["value"])

    task = asyncio.create_task(collect())
    await action()
    await asyncio.sleep(wait_s)
    sub.close()
    await task
    return seen


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('PTP Property 0000500f changed, "iso" to "800"', 0x500F),
        ('PTP Property 0000d100 changed, "shutterspeed2" to "1/80"', 0xD100),
        ('PTP Property 0000d0b5 changed, "ISOControlSensitivity" to "320"', 0xD0B5),
        ('PTP Property 500f changed, "ISO Speed" to "400"', 0x500F),
        ("PTP Property d1a2 changed", 0xD1A2),
        ('PTP Property 500D changed, "Exposure Time"', 0x500D),
        ("Unknown event 4004", None),
        ("", None),
    ],
)
def test_parse_property_event(text: str, code: int | None) -> None:
    assert parse_property_event(text) == code


async def test_body_change_publishes_new_value(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    await connected_client.get("/api/v1/settings")  # warm the cache
    seen = await _changes(app, "iso", lambda: asyncio.to_thread(fake_camera.body_set, "iso", "800"))
    assert seen == ["800"]
    r = await connected_client.get("/api/v1/settings/iso")
    assert r.json()["value"] == "800"


async def test_unmapped_property_code_is_ignored(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    svc = app.state.camera_service
    gets = fake_camera.calls.get("get_config", 0)
    svc._prop_sync.on_codes([0x9999])
    await asyncio.sleep(0.3)
    assert fake_camera.calls.get("get_config", 0) == gets


async def test_apps_own_write_is_not_echoed(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    fake_camera._prop_events = True  # the body announces the app's own writes too
    svc = app.state.camera_service
    seen = await _changes(app, "iso", lambda: svc.set_setting("iso", "400"))
    assert seen == ["400"]  # only the write's own SETTING_CHANGED


async def test_burst_is_debounced_to_one_refresh(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    await connected_client.get("/api/v1/settings")

    async def burst() -> None:
        for v in ("200", "400", "800", "1600"):
            await asyncio.to_thread(fake_camera.body_set, "iso", v)
            await asyncio.sleep(0.01)

    seen = await _changes(app, "iso", burst, wait_s=0.6)
    assert seen == ["1600"]


async def test_unknown_names_are_never_refreshed_and_no_full_tree_read(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    svc = app.state.camera_service
    svc._invalidate_cache()  # empty settings cache: nothing is known to exist
    svc._name_cache = {}
    gets = fake_camera.calls.get("get_config", 0)
    lists = fake_camera.calls.get("list_config", 0)
    svc._prop_sync.on_codes([0x500E, 0x500B])
    await asyncio.sleep(0.4)
    assert fake_camera.calls.get("get_config", 0) == gets
    assert fake_camera.calls.get("list_config", 0) == lists


async def test_status_reports_property_events_once_seen(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    assert (await connected_client.get("/api/v1/camera")).json()["property_events"] is False
    svc = app.state.camera_service
    await connected_client.get("/api/v1/settings")
    svc._on_property_code(0x500F)
    assert (await connected_client.get("/api/v1/camera")).json()["property_events"] is True


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ('PTP Property 0000500f changed, "iso" to "800"', (0x500F, "iso", "800")),
        (
            'PTP Property 0000500d changed, "shutterspeed" to "0.0125s"',
            (0x500D, "shutterspeed", "0.0125s"),
        ),
        ('PTP Property 00005007 changed, "f-number" to "f/4.5"', (0x5007, "f-number", "f/4.5")),
        (
            'PTP Property 0000d100 changed, "shutterspeed2" to "1/80"',
            (0xD100, "shutterspeed2", "1/80"),
        ),
        (
            'PTP Property 0000d0b5 changed, "ISOControlSensitivity" to "320"',
            (0xD0B5, "ISOControlSensitivity", "320"),
        ),
        ('PTP Property 0000500a changed, "focusmode" to "AF-C"', (0x500A, "focusmode", "AF-C")),
        ("PTP Property 500f changed", (0x500F, None, None)),
    ],
)
def test_parse_property_change(text: str, parsed: tuple) -> None:
    assert parse_property_change(text) == parsed


async def test_reported_value_is_applied_without_reread(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    await connected_client.get("/api/v1/settings")
    svc = app.state.camera_service
    gets = fake_camera.calls.get("get_config", 0)

    async def go() -> None:
        svc._on_property_code(0x500F, "iso", "800")

    seen = await _changes(app, "iso", go)
    assert seen == ["800"]
    assert fake_camera.calls.get("get_config", 0) == gets
    assert svc.cached_setting("iso").value == "800"


async def test_unparsable_value_falls_back_to_reread(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    await connected_client.get("/api/v1/settings")
    svc = app.state.camera_service
    fake_camera._values["iso"] = "1600"

    async def go() -> None:
        svc._on_property_code(0x500F, "iso", "not-a-choice")

    assert await _changes(app, "iso", go) == ["1600"]


async def test_reported_name_wins_over_code(
    app: FastAPI, connected_client, fake_camera: FakeCamera
) -> None:
    await connected_client.get("/api/v1/settings")
    svc = app.state.camera_service
    fake_camera._values["iso"] = "3200"

    async def go() -> None:
        svc._on_property_code(0xD0B5, "iso", None)  # unknown code, known name

    assert await _changes(app, "iso", go) == ["3200"]
