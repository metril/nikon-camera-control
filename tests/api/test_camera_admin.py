from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.services.camera_admin import CameraAdminService

C = "/api/v1/camera"
NOW = 1_800_000_000.0


def inject_clock(app: FastAPI, now: float = NOW) -> None:
    st = app.state
    st.services.get(
        "camera_admin",
        lambda: CameraAdminService(st.camera_service, st.event_bus, clock=lambda: now),
    )


async def test_datetime_read(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    inject_clock(app)
    r = await connected_client.get(f"{C}/datetime")
    body = r.json()
    cam = datetime.fromtimestamp(1_700_000_000, UTC)
    assert r.status_code == 200 and datetime.fromisoformat(body["camera_time"]) == cam
    assert body["offset_s"] == 1_700_000_000 - NOW


async def test_datetime_sync_host(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app)
    r = await connected_client.put(f"{C}/datetime", json={"mode": "host"})
    assert r.status_code == 200, r.text
    assert r.json()["offset_s"] == 0
    assert fake_camera.get_config("datetime").value == int(NOW)
    assert (await connected_client.get(f"{C}/datetime")).json()["offset_s"] == 0


async def test_datetime_explicit(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app)
    r = await connected_client.put(
        f"{C}/datetime", json={"mode": "explicit", "time": "2030-01-01T00:00:00Z"}
    )
    assert r.status_code == 200
    assert fake_camera.get_config("datetime").value == 1_893_456_000
    assert r.json()["offset_s"] == 1_893_456_000 - NOW


async def test_datetime_body_validation(connected_client: httpx.AsyncClient) -> None:
    for body in (
        {"mode": "explicit"},
        {"mode": "host", "time": "2030-01-01T00:00:00Z"},
        {"mode": "nope"},
    ):
        assert (await connected_client.put(f"{C}/datetime", json=body)).status_code == 422


async def test_disconnected_503(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{C}/datetime")).status_code == 503
    assert (await client.put(f"{C}/datetime", json={"mode": "host"})).status_code == 503
    assert (await client.get(f"{C}/capture-target")).status_code == 503
    assert (await client.put(f"{C}/capture-target", json={"value": "ram"})).status_code == 503


async def test_datetime_write_409_under_foreign_lease(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    async with app.state.camera_service.lease("timelapse"):
        r = await connected_client.put(f"{C}/datetime", json={"mode": "host"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
        assert (await connected_client.get(f"{C}/datetime")).status_code == 200  # read is fine


async def test_capture_target_get_set(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    r = await connected_client.get(f"{C}/capture-target")
    assert r.json() == {"value": "Memory card", "choices": ["Internal RAM", "Memory card"]}
    r = await connected_client.put(f"{C}/capture-target", json={"value": "ram"})
    assert r.status_code == 200 and r.json()["value"] == "Internal RAM"
    assert fake_camera.get_config("capturetarget").value == "Internal RAM"
    r = await connected_client.put(f"{C}/capture-target", json={"value": "card"})
    assert r.json()["value"] == "Memory card"
    r = await connected_client.put(f"{C}/capture-target", json={"value": "internal ram"})
    assert r.json()["value"] == "Internal RAM"
    r = await connected_client.put(f"{C}/capture-target", json={"value": "floppy"})
    assert r.status_code == 422 and r.json()["error"]["details"]["choices"]


async def test_capture_target_refused_under_lease(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    async with app.state.camera_service.lease("timelapse"):
        r = await connected_client.put(f"{C}/capture-target", json={"value": "ram"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    assert fake_camera.get_config("capturetarget").value == "Memory card"
