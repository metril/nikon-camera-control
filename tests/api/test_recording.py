import asyncio
import time

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed

R = "/api/v1/recording"


async def _state(c: httpx.AsyncClient) -> str:
    return (await c.get("/api/v1/camera")).json()["state"]


async def test_start_status_stop_happy_path(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    r = await c.post(f"{R}/start", json={"max_seconds": 60})
    assert r.status_code == 200
    b = r.json()
    assert b["active"] and b["max_seconds"] == 60 and b["state"] == "recording"
    assert (await c.get(R)).json()["active"] is True
    assert (await c.get("/api/v1/camera")).json()["leased_by"] == "recording"

    r = await c.post(f"{R}/stop")
    b = r.json()
    assert r.status_code == 200 and b["active"] is False and b["ended_reason"] == "user"
    assert b["last_clip"]["name"].endswith(".MOV") and b["last_clip"]["size"] > 0
    assert await _state(c) == "idle" and not fake_camera.viewfinder_on
    assert (await c.get("/api/v1/camera")).json()["leased_by"] is None
    assert (await c.get(R)).json()["last_clip"] == b["last_clip"]


async def test_capture_and_settings_writes_409_while_recording(
    connected_client: httpx.AsyncClient,
) -> None:
    c = connected_client
    await c.post(f"{R}/start", json={})
    assert (await c.post("/api/v1/capture", json={})).status_code == 409
    r = await c.put("/api/v1/settings/iso", json={"value": "200"})
    assert r.status_code == 409
    assert (await c.post(f"{R}/stop")).status_code == 200


async def test_start_twice_and_stop_idle_are_409(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    r = await c.post(f"{R}/stop")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    await c.post(f"{R}/start", json={})
    assert (await c.post(f"{R}/start", json={})).status_code == 409
    await c.post(f"{R}/stop")


async def test_disconnected_is_503(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{R}/start", json={})
    assert r.status_code == 503


async def test_max_seconds_validated(connected_client: httpx.AsyncClient) -> None:
    for bad in (0, 1800, -5):
        r = await connected_client.post(f"{R}/start", json={"max_seconds": bad})
        assert r.status_code == 422


async def test_internal_ram_capture_target_is_warning_not_refusal(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    await app.state.camera_service.set_setting("capturetarget", "Internal RAM")
    r = await connected_client.post(f"{R}/start", json={})
    assert r.status_code == 200 and "Internal RAM" in r.json()["warning"]
    assert (await connected_client.post(f"{R}/stop")).status_code == 200


async def test_start_rejected_by_camera_is_clear_and_rolls_back(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    fake_camera.fail_next("set_config", exc=CameraOperationFailed("not in movie mode"))
    r = await connected_client.post(f"{R}/start", json={})
    assert r.status_code == 502 and "movie mode" in r.json()["error"]["message"]
    assert await _state(connected_client) == "idle"
    assert (await connected_client.get(R)).json()["active"] is False


async def test_download_after_job_writes_into_recordings_dir(
    connected_client: httpx.AsyncClient, tmp_dirs
) -> None:
    c = connected_client
    await c.post(f"{R}/start", json={"download_after": True})
    job_id = (await c.post(f"{R}/stop")).json()["job_id"]
    assert job_id
    deadline = time.monotonic() + 3
    while (job := (await c.get(f"/api/v1/jobs/{job_id}")).json())["status"] != "completed":
        assert time.monotonic() < deadline and job["status"] != "failed", job
        await asyncio.sleep(0.01)
    files = list((tmp_dirs.output_dir / "recordings").glob("*.MOV"))
    assert len(files) == 1


async def test_snapshot_works_during_recording(connected_client: httpx.AsyncClient) -> None:
    await connected_client.post(f"{R}/start", json={})
    r = await connected_client.get("/api/v1/liveview/snapshot")
    assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff"
    await connected_client.post(f"{R}/stop")


async def test_app_shutdown_stops_active_recording(
    app: FastAPI, client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await app.state.camera_service.connect()
    await client.post(f"{R}/start", json={})
    assert fake_camera.get_config("movie").value
    await app.state.services.aclose()
    assert not fake_camera.get_config("movie").value
    assert app.state.camera_service.status().leased_by is None


def test_openapi_operation_ids(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    assert paths[f"{R}/start"]["post"]["operationId"] == "start_recording"
    assert paths[f"{R}/stop"]["post"]["operationId"] == "stop_recording"
    assert paths[R]["get"]["operationId"] == "get_recording"
    snap = paths["/api/v1/liveview/snapshot"]["get"]["responses"]["200"]["content"]
    assert snap["image/jpeg"]["schema"] == {"type": "string", "format": "binary"}
