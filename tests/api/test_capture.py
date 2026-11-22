import asyncio
import re
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera

C = "/api/v1/capture"


async def test_capture_downloads_and_names(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs
) -> None:
    r = await connected_client.post(C, json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["files"]) == 1 and len(body["camera_files"]) == 1
    f = body["files"][0]
    assert re.fullmatch(r"\d{8}_\d{6}_DSC_\d{4}\.JPG", f["name"]) and f["kind"] == "image"
    p: Path = tmp_dirs.output_dir / f["path"]
    assert await asyncio.to_thread(p.stat) and f["size"] > 0
    assert (await connected_client.get("/api/v1/camera")).json()["state"] == "idle"
    assert (await connected_client.get("/api/v1/files")).json()["total"] == 1


async def test_capture_raw_plus_jpeg_two_files_with_prefix(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    await app.state.camera_service.set_setting("imagequality", "NEF+JPEG Fine")
    r = await connected_client.post(C, json={"filename_prefix": "../my shot!"})
    names = [f["name"] for f in r.json()["files"]]
    assert len(names) == 2 and {n.rsplit(".", 1)[1] for n in names} == {"NEF", "JPG"}
    assert all(n.startswith("my_shot_2") and "/" not in n for n in names)


async def test_capture_names_never_collide_within_a_second(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    # same camera file name twice in the same second (counter wrap / card swap) must not overwrite
    await connected_client.post(C, json={"download": False})  # builds the service
    svc = app.state.services.get("capture", lambda: None)
    from backend.camera.backend import CameraFilePath

    one = (await app.state.camera_service.capture())[0]
    files = [CameraFilePath(one.folder, one.name)] * 2
    paths = await svc._download(
        files, app.state.output_dir, owner=None, name_prefix="", delete_from_camera=False
    )
    assert len(set(paths)) == 2 and all(p.stat().st_size > 0 for p in paths)


async def test_capture_no_download_and_delete_from_camera(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    r = await connected_client.post(C, json={"download": False})
    assert r.json()["files"] == [] and len(r.json()["camera_files"]) == 1
    r = await connected_client.post(C, json={"delete_from_camera": True})
    assert r.status_code == 200 and len(r.json()["files"]) == 1
    assert fake_camera.calls["delete_file"] == 1


async def test_trigger_only(connected_client: httpx.AsyncClient, fake_camera: FakeCamera) -> None:
    r = await connected_client.post(f"{C}/trigger")
    assert r.json() == {"ok": True} and fake_camera.calls["trigger"] == 1
    assert fake_camera.calls.get("read_file", 0) == 0


async def test_capture_busy_under_other_lease(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    async with app.state.camera_service.lease("timelapse"):
        r = await connected_client.post(C, json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
        assert (await connected_client.post(f"{C}/trigger")).status_code == 409


async def test_capture_card_full_leaves_idle(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    fake_camera.card_full()
    r = await connected_client.post(C, json={})
    assert r.status_code == 507 and r.json()["error"]["code"] == "STORAGE_FULL"
    state = (await connected_client.get("/api/v1/camera")).json()["state"]
    assert state == "idle", state


async def test_capture_hang_times_out(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    app.state.config_store.update({"camera": {"capture_timeout_s": 0.1}})
    fake_camera.hang("capture")
    try:
        r = await asyncio.wait_for(connected_client.post(C, json={}), 5)
        assert r.status_code == 504 and r.json()["error"]["code"] == "CAMERA_TIMEOUT"
    finally:
        fake_camera.release_all()
        await asyncio.sleep(0.05)


async def test_capture_when_not_connected(client: httpx.AsyncClient) -> None:
    r = await client.post(C, json={})
    assert r.status_code == 503 and r.json()["error"]["code"] == "CAMERA_NOT_CONNECTED"


async def test_capture_to_session_folder(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    from backend.api.v1.capture import get_capture  # noqa: F401

    await connected_client.post(C, json={})  # builds the service
    svc = app.state.services.get("capture", lambda: None)
    dest = app.state.output_dir / "sess"
    async with app.state.camera_service.lease("tl"):
        paths = await svc.capture_to(dest, owner="tl", name_prefix="f001_")
    assert len(paths) == 1 and paths[0].parent == dest and paths[0].name.startswith("f001_")
    assert not list(dest.glob("*.part"))
    r = await connected_client.get("/api/v1/files", params={"folder": "sess"})
    assert r.json()["total"] == 1  # index invalidated


async def test_openapi_ids(app: FastAPI) -> None:
    p = app.openapi()["paths"]
    assert p[C]["post"]["operationId"] == "capture_photo"
    assert p[f"{C}/trigger"]["post"]["operationId"] == "trigger_capture"
