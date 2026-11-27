from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core import clock
from backend.services.camera_admin import CameraAdminService

C = "/api/v1/camera"
NOW = 1_800_000_000.0


def inject_clock(app: FastAPI, now: float = NOW, server_offset_s: int = 0) -> None:
    st = app.state
    st.services.get(
        "camera_admin",
        lambda: CameraAdminService(
            st.camera_service,
            st.event_bus,
            clock=lambda: now,
            local_offset_s=lambda _t: server_offset_s,
        ),
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


async def test_datetime_sync_leaves_live_view_first(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app)
    fake_camera.capture_preview()  # live view on
    assert fake_camera.viewfinder_on
    r = await connected_client.put(f"{C}/datetime", json={"mode": "host"})
    assert r.status_code == 200
    assert not fake_camera.viewfinder_on
    assert fake_camera.get_config("datetime").value == int(NOW)


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


NEW_YORK = -5 * 3600  # a non-UTC server zone (no DST in the injected offset)


async def test_datetime_host_with_browser_offset_on_utc_server(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app, server_offset_s=0)
    r = await connected_client.put(
        f"{C}/datetime", json={"mode": "host", "utc_offset_minutes": 120}
    )
    assert r.status_code == 200, r.text
    assert fake_camera.get_config("datetime").value == int(NOW) + 7200
    body = r.json()
    wall = datetime.fromtimestamp(NOW + 7200, UTC).replace(tzinfo=None)
    assert datetime.fromisoformat(body["camera_wall_time"]) == wall
    assert body["camera_epoch"] == int(NOW) + 7200 and body["host_utc_offset_minutes"] == 0


async def test_datetime_host_with_browser_offset_on_non_utc_server(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app, server_offset_s=NEW_YORK)
    r = await connected_client.put(
        f"{C}/datetime", json={"mode": "host", "utc_offset_minutes": 120}
    )
    # camera must show UTC+2 wall time; the raw epoch is that wall time read in the server zone
    assert fake_camera.get_config("datetime").value == int(NOW) + 7200 - NEW_YORK
    body = r.json()
    wall = datetime.fromtimestamp(NOW + 7200, UTC).replace(tzinfo=None)
    assert datetime.fromisoformat(body["camera_wall_time"]) == wall
    assert body["host_utc_offset_minutes"] == -300


async def test_datetime_host_without_offset_uses_server_zone(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app, server_offset_s=NEW_YORK)
    r = await connected_client.put(f"{C}/datetime", json={"mode": "host"})
    assert fake_camera.get_config("datetime").value == int(NOW)  # server's own wall time
    wall = datetime.fromtimestamp(NOW + NEW_YORK, UTC).replace(tzinfo=None)
    assert datetime.fromisoformat(r.json()["camera_wall_time"]) == wall


async def test_datetime_explicit_with_offset(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app, server_offset_s=NEW_YORK)
    r = await connected_client.put(
        f"{C}/datetime",
        json={"mode": "explicit", "time": "2030-01-01T00:00:00Z", "utc_offset_minutes": -480},
    )
    assert r.status_code == 200
    assert fake_camera.get_config("datetime").value == 1_893_456_000 - 8 * 3600 - NEW_YORK
    assert r.json()["camera_wall_time"].startswith("2029-12-31T16:00:00")
    bad = await connected_client.put(
        f"{C}/datetime", json={"mode": "host", "utc_offset_minutes": 9999}
    )
    assert bad.status_code == 422


async def test_datetime_sync_uses_app_zone(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    inject_clock(app)
    clock.set_zone("Pacific/Kiritimati")  # UTC+14
    try:
        r = await connected_client.put(f"{C}/datetime", json={"mode": "host"})
        assert r.status_code == 200, r.text
        assert r.json()["app_utc_offset_minutes"] == 840
        assert fake_camera.get_config("datetime").value == int(NOW) + 14 * 3600
    finally:
        clock.set_zone(None)


async def test_datetime_sync_host_with_browser_offset(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    """The exact body the web UI sends when no app time zone is set."""
    inject_clock(app)
    for off in (0, -300, 330, 840, -720):
        r = await connected_client.put(
            f"{C}/datetime", json={"mode": "host", "utc_offset_minutes": off}
        )
        assert r.status_code == 200, (off, r.text)
