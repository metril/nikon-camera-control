import asyncio
import re
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core.config_store import CameraConfig

C = "/api/v1/capture"


async def test_capture_downloads_and_names(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs
) -> None:
    r = await connected_client.post(C, json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["files"]) == 1 and len(body["camera_files"]) == 1
    f = body["files"][0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}-DSC_\d{4}\.JPG", f["name"])
    assert f["kind"] == "image"
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
    assert all(n.startswith("my-shot-2") and "/" not in n for n in names)


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
        files, app.state.storage.root(), owner=None, name_prefix="", delete_from_camera=False
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
    store = app.state.config_store
    short = CameraConfig.model_construct(
        **{**store.config.camera.model_dump(), "capture_timeout_s": 0.1}
    )
    store._config = store.config.model_copy(update={"camera": short})  # noqa: SLF001
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
    dest = app.state.storage.root() / "sess"
    async with app.state.camera_service.lease("tl"):
        paths = await svc.capture_to(dest, owner="tl", name_prefix="f001-")
    assert len(paths) == 1 and paths[0].parent == dest and paths[0].name.startswith("f001-")
    assert not list(dest.glob("*.part"))
    r = await connected_client.get("/api/v1/files", params={"folder": "sess"})
    assert r.json()["total"] == 1  # index invalidated


async def test_openapi_ids(app: FastAPI) -> None:
    p = app.openapi()["paths"]
    assert p[C]["post"]["operationId"] == "capture_photo"
    assert p[f"{C}/trigger"]["post"]["operationId"] == "trigger_capture"


async def test_trigger_twice_then_capture_returns_only_its_own_file(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    for _ in range(2):
        assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    r = await connected_client.post(C, json={})
    assert len(r.json()["camera_files"]) == 1 and len(r.json()["files"]) == 1
    assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    await app.state.camera_service.set_setting("imagequality", "NEF+JPEG Fine")
    r = await connected_client.post(C, json={"download": False})
    assert len(r.json()["camera_files"]) == 2


async def test_body_shot_before_capture_is_not_attributed_to_it(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    stray = fake_camera.press_shutter()
    assert len(stray) == 1
    r = await connected_client.post(C, json={"download": False})
    names = [f["name"] for f in r.json()["camera_files"]]
    assert len(names) == 1 and names[0] != stray[0].name


async def test_stray_file_between_frames_is_not_part_of_a_frame(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    cam = app.state.camera_service
    first = await cam.capture()
    fake_camera.press_shutter()
    second = await cam.capture()
    assert len(first) == 1 and len(second) == 1 and first != second


async def test_trigger_then_immediate_capture_and_trigger_in_live_view(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await connected_client.post(f"{C}/trigger")
    assert len(await app.state.camera_service.capture()) == 1
    assert (await connected_client.get("/api/v1/camera")).json()["state"] == "idle"


async def test_stray_file_is_downloaded_in_background_and_announced(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs
) -> None:
    sub = app.state.event_bus.subscribe()
    stray = fake_camera.press_shutter()
    r = await connected_client.post(C, json={"download": False})  # builds CaptureService
    assert r.status_code == 200
    deadline = asyncio.get_running_loop().time() + 5
    while len(list(tmp_dirs.output_dir.glob("**/*-" + stray[0].name))) != 1:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    assert not app.state.camera_service.stray_files
    seen = []
    while not sub._queue.empty():
        ev = sub._queue.get_nowait()
        if ev is not None and ev.type.value == "capture_complete":
            seen.append(ev.data["files"])
    sub.close()
    assert [{"folder": stray[0].folder, "name": stray[0].name}] in seen


async def test_trigger_refused_with_ram_target(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await app.state.camera_service.set_setting("capturetarget", "Internal RAM")
    r = await connected_client.post(f"{C}/trigger")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    assert fake_camera.calls.get("trigger", 0) == 0


async def test_configured_prefix_used_unless_request_gives_one(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    app.state.config_store.update({"camera": {"filename_prefix": "wedding day"}})
    a = (await connected_client.post(C, json={})).json()["files"][0]["name"]
    b = (await connected_client.post(C, json={"filename_prefix": "own"})).json()["files"][0]["name"]
    assert a.startswith("wedding-day-2") and b.startswith("own-2")


async def test_download_photos_and_prefix_config_defaults_and_limit(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    cam = (await connected_client.get("/api/v1/config")).json()["camera"]
    assert cam["download_photos"] is True and cam["filename_prefix"] is None
    r = await connected_client.patch(
        "/api/v1/config", json={"camera": {"filename_prefix": "x" * 41}}
    )
    assert r.status_code == 422


async def test_trigger_file_is_never_downloaded_or_deleted(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs
) -> None:
    assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    r = await connected_client.post(C, json={})
    assert len(r.json()["files"]) == 1
    await asyncio.sleep(0.3)  # any background stray task would have run by now
    assert len(list(tmp_dirs.output_dir.glob("**/*.JPG"))) == 1
    assert fake_camera.calls.get("delete_file", 0) == 0
    assert (await connected_client.get("/api/v1/camera/files?recursive=true")).json()["total"] == 2


async def test_trigger_refused_with_bulb_shutter(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await app.state.camera_service.set_setting("shutterspeed", "Bulb")
    r = await connected_client.post(f"{C}/trigger")
    assert r.status_code >= 400
    assert fake_camera.calls.get("trigger", 0) == 0


def _delay_events(fake: FakeCamera, delays: list[float]) -> None:
    """Hold back the shot's FILE_ADDED events after trigger(): event i arrives delays[i] s later."""
    orig = fake.trigger

    def trigger() -> None:
        orig()
        with fake._cond:
            held = [fake._events.popleft() for _ in range(len(fake._events))]
        for ev, d in zip(held, delays, strict=False):

            def add(ev=ev) -> None:
                with fake._cond:
                    fake._events.append(ev)
                    fake._cond.notify_all()

            threading.Timer(d, add).start()

    fake.trigger = trigger  # type: ignore[method-assign]


async def _assert_claimed(app: FastAPI, client: httpx.AsyncClient, tmp_dirs, n_files: int) -> None:
    cs = app.state.camera_service
    assert len(app.state.services.get("capture", lambda: None)._triggered) == n_files
    r = await client.post(C, json={})
    assert len(r.json()["files"]) == 1
    await asyncio.sleep(0.3)  # a wrongly attributed stray would be fetched in the background
    assert len(list(tmp_dirs.output_dir.glob("**/*.JPG"))) == 1
    assert not cs.stray_files


async def test_trigger_claims_delayed_file(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs
) -> None:
    app.state.camera_service._quiet_override = 0.5
    _delay_events(fake_camera, [0.5])
    assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    await _assert_claimed(app, connected_client, tmp_dirs, 1)


async def test_trigger_claims_split_raw_jpeg_pair(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs
) -> None:
    app.state.camera_service._quiet_override = 0.6
    await app.state.camera_service.set_setting("imagequality", "NEF+JPEG Fine")
    _delay_events(fake_camera, [0.0, 0.4])
    assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    cs = app.state.services.get("capture", lambda: None)
    assert {f.name.rsplit(".", 1)[1] for f in cs._triggered} == {"NEF", "JPG"}
    await app.state.camera_service.set_setting("imagequality", "JPEG Fine")
    r = await connected_client.post(C, json={})
    assert len(r.json()["files"]) == 1
    await asyncio.sleep(0.3)
    assert len([p for p in tmp_dirs.output_dir.glob("**/*") if p.is_file()]) == 1


async def test_trigger_chatter_does_not_end_collection(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs
) -> None:
    app.state.camera_service._quiet_override = 0.5
    fake_camera._chatter = True
    _delay_events(fake_camera, [0.6])
    assert (await connected_client.post(f"{C}/trigger")).status_code == 200
    fake_camera._chatter = False
    await _assert_claimed(app, connected_client, tmp_dirs, 1)
