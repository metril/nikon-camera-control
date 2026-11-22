import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.camera.fake import CARD_FOLDER, FakeCamera
from backend.core.errors import CameraOperationFailed

F = "/api/v1/camera/files"
J = "/api/v1/jobs"


async def _shoot(c: httpx.AsyncClient, app: FastAPI, quality: str, n: int = 1) -> None:
    svc = app.state.camera_service
    await svc.set_setting("imagequality", quality)
    for _ in range(n):
        await svc.capture()


async def _wait_job(c: httpx.AsyncClient, jid: str, done: Callable[[dict[str, Any]], bool]) -> Any:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        j = (await c.get(f"{J}/{jid}")).json()
        if done(j):
            return j
        await asyncio.sleep(0.02)
    raise AssertionError(f"job did not settle: {j}")


def _finished(j: dict[str, Any]) -> bool:
    return j["status"] in ("completed", "failed", "cancelled")


async def test_folders_one_level(connected_client: httpx.AsyncClient) -> None:
    r = await connected_client.get("/api/v1/camera/folders")
    assert r.json() == {
        "folder": "/",
        "folders": [{"name": "store_00010001", "path": "/store_00010001"}],
    }
    r = await connected_client.get("/api/v1/camera/folders", params={"folder": "/store_00010001"})
    assert r.json()["folders"][0]["path"] == "/store_00010001/DCIM"
    r = await connected_client.get("/api/v1/camera/folders", params={"folder": "/nope"})
    assert r.status_code == 404


async def test_list_types_and_pagination(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine", 2)
    await _shoot(c, app, "NEF (Raw)", 1)
    await _shoot(c, app, "NEF+JPEG Fine", 1)
    r = await c.get(F, params={"folder": CARD_FOLDER})
    body = r.json()
    assert body["total"] == 5
    types = sorted(i["type"] for i in body["items"])
    assert types == ["jpeg", "jpeg", "jpeg", "raw", "raw"]
    assert all(i["downloaded"] is False and i["size"] > 0 for i in body["items"])
    r = await c.get(F, params={"folder": CARD_FOLDER, "page": 2, "limit": 2})
    assert r.json()["total"] == 5 and len(r.json()["items"]) == 2 and r.json()["page"] == 2
    r = await c.get(F, params={"folder": CARD_FOLDER, "page": 3, "limit": 2})
    assert len(r.json()["items"]) == 1
    # recursive from the root finds the same files
    r = await c.get(F, params={"folder": "/", "recursive": "true"})
    assert r.json()["total"] == 5
    assert (await c.get(F, params={"folder": "/", "recursive": "false"})).json()["total"] == 0


async def test_listing_is_cached_and_invalidated_on_capture(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine")
    await c.get(F, params={"folder": CARD_FOLDER})
    n = fake_camera.calls["list_files"]
    await c.get(F, params={"folder": CARD_FOLDER})
    assert fake_camera.calls["list_files"] == n  # served from cache
    await app.state.camera_service.capture()
    await asyncio.sleep(0.05)  # event delivery
    r = await c.get(F, params={"folder": CARD_FOLDER})
    assert r.json()["total"] == 2 and fake_camera.calls["list_files"] == n + 1


async def test_listing_error_surfaces_not_partial(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    """Regression: backend errors used to be swallowed into a partial/empty list."""
    await _shoot(connected_client, app, "JPEG Fine")
    fake_camera.fail_next("list_files", exc=CameraOperationFailed("boom"))
    r = await connected_client.get(F, params={"folder": "/", "recursive": "true"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "CAMERA_OPERATION_FAILED"
    # failure is not cached
    assert (await connected_client.get(F, params={"folder": "/", "recursive": "true"})).json()[
        "total"
    ] == 1


async def test_not_connected(client: httpx.AsyncClient) -> None:
    r = await client.get(F, params={"folder": CARD_FOLDER})
    assert r.status_code == 503


async def test_download_one_and_cleanup(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    await _shoot(connected_client, app, "JPEG Fine")
    name = (await connected_client.get(F, params={"folder": CARD_FOLDER})).json()["items"][0][
        "name"
    ]
    r = await connected_client.get(f"{F}{CARD_FOLDER}/{name}")
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
    assert "image/jpeg" in r.headers["content-type"]
    assert name in r.headers["content-disposition"]
    tmp = tmp_dirs.data_dir / "tmp"
    assert not tmp.exists() or list(tmp.iterdir()) == []  # background cleanup ran
    r = await connected_client.get(f"{F}{CARD_FOLDER}/NOPE.JPG")
    assert r.status_code == 404 and r.json()["error"]["code"] == "FILE_NOT_FOUND"
    assert list(tmp.iterdir()) == []


async def test_delete_and_lease_conflict(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine")
    name = (await c.get(F, params={"folder": CARD_FOLDER})).json()["items"][0]["name"]
    async with app.state.camera_service.lease("timelapse"):
        r = await c.delete(f"{F}{CARD_FOLDER}/{name}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
    r = await c.delete(f"{F}{CARD_FOLDER}/{name}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await c.get(F, params={"folder": CARD_FOLDER})).json()["total"] == 0
    assert (await c.delete(f"{F}{CARD_FOLDER}/{name}")).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/store_00010001/../etc/passwd",
        "/store_00010001/%2e%2e/%2e%2e/passwd",
        "/store_00010001/DCIM/..%2f..%2fsecret",
        "/store_00010001/DCIM/100ND500/..",
    ],
)
async def test_traversal_rejected(connected_client: httpx.AsyncClient, path: str) -> None:
    for method in (connected_client.get, connected_client.delete):
        r = await method(f"{F}{path}")
        assert r.status_code in (400, 404), (method, path, r.status_code)
        assert r.status_code != 200


async def test_bad_folder_and_names_rejected(connected_client: httpx.AsyncClient) -> None:
    for folder in ("relative", "/a/../b", "/a\x00b"):
        r = await connected_client.get(F, params={"folder": folder})
        assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_NOT_ALLOWED", folder
    r = await connected_client.get(f"{F}{CARD_FOLDER}/a%00b.jpg")
    assert r.status_code == 400
    r = await connected_client.post(f"{F}/download-all", json={"folder": "../x"})
    assert r.status_code == 400


async def test_download_all_happy_and_only_new(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    c = connected_client
    await _shoot(c, app, "NEF+JPEG Fine", 2)
    r = await c.post(f"{F}/download-all", json={})
    assert r.status_code == 202 and r.json()["kind"] == "download_all"
    j = await _wait_job(c, r.json()["id"], _finished)
    assert j["status"] == "completed"
    res = j["result"]
    assert (res["downloaded"], res["skipped"], res["failed"]) == (4, 0, 0)
    out = tmp_dirs.output_dir / "camera"
    assert len(list(out.iterdir())) == 4
    ledger = (tmp_dirs.data_dir / "downloaded.jsonl").read_text().splitlines()
    assert len(ledger) == 4
    items = (await c.get(F, params={"folder": CARD_FOLDER})).json()["items"]
    assert all(i["downloaded"] for i in items)
    # second run: nothing new (regression: "new" used to re-download everything)
    j = await _wait_job(c, (await c.post(f"{F}/download-all", json={})).json()["id"], _finished)
    assert (j["result"]["downloaded"], j["result"]["skipped"]) == (0, 4)
    assert len(list(out.iterdir())) == 4
    j = await _wait_job(
        c,
        (await c.post(f"{F}/download-all", json={"only_new": False})).json()["id"],
        _finished,
    )
    assert j["result"]["downloaded"] == 4


async def test_download_all_delete_after(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine", 2)
    await c.get(F, params={"folder": CARD_FOLDER})  # warm cache
    j = await _wait_job(
        c,
        (await c.post(f"{F}/download-all", json={"delete_after": True})).json()["id"],
        _finished,
    )
    assert j["result"]["downloaded"] == 2
    assert (await c.get(F, params={"folder": CARD_FOLDER})).json()["total"] == 0


async def test_download_all_one_failure_continues(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine", 3)
    fake_camera.fail_next("read_file", exc=CameraOperationFailed("bad file"))
    j = await _wait_job(c, (await c.post(f"{F}/download-all", json={})).json()["id"], _finished)
    assert j["status"] == "completed"
    assert (j["result"]["downloaded"], j["result"]["failed"]) == (2, 1)
    assert len(j["result"]["failed_names"]) == 1
    # only the failed one is retried
    j = await _wait_job(c, (await c.post(f"{F}/download-all", json={})).json()["id"], _finished)
    assert (j["result"]["downloaded"], j["result"]["skipped"]) == (1, 2)


async def test_download_all_cancel_midway(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine", 4)
    fake_camera.set_latency("read_file", 0.1)
    jid = (await c.post(f"{F}/download-all", json={})).json()["id"]
    j = await _wait_job(c, jid, lambda j: j["status"] == "running" and "(2/" in j["message"])
    r = await c.delete(f"{J}/{jid}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    fake_camera.set_latency("read_file", 0)
    await asyncio.sleep(0.15)  # let the in-flight worker call drain
    ledger_file = app.state.data_dir / "downloaded.jsonl"
    ledger = ledger_file.read_text().splitlines() if ledger_file.exists() else []
    assert len(ledger) < 4
    assert j["message"]


async def test_download_all_exclusive_conflict(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    await _shoot(c, app, "JPEG Fine", 2)
    ev = fake_camera.hang("read_file")
    jid = (await c.post(f"{F}/download-all", json={})).json()["id"]
    r = await c.post(f"{F}/download-all", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
    assert r.json()["error"]["details"]["job_id"] == jid
    ev.set()
    await _wait_job(c, jid, _finished)
    fake_camera.release_all()
    r = await c.post(f"{F}/download-all", json={})
    assert r.status_code == 202
    await _wait_job(c, r.json()["id"], _finished)


async def test_download_all_listing_error_fails_job(
    app: FastAPI, fake_camera: FakeCamera, connected_client: httpx.AsyncClient
) -> None:
    fake_camera.fail_next("list_folders", exc=CameraOperationFailed("nope"))
    jid = (await connected_client.post(f"{F}/download-all", json={})).json()["id"]
    j = await _wait_job(connected_client, jid, _finished)
    assert j["status"] == "failed" and j["error_code"] == "CAMERA_OPERATION_FAILED"


async def test_temp_dir_removed_even_if_client_disconnects_mid_stream(tmp_path: Any) -> None:
    from backend.api.v1.camera_files import _TempFileResponse

    d = tmp_path / "dl"
    d.mkdir()
    (d / "a.bin").write_bytes(b"x" * 100_000)

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(msg: dict[str, Any]) -> None:
        if msg["type"] == "http.response.body":
            raise OSError("client went away")

    resp = _TempFileResponse(d / "a.bin", d, filename="a.bin")
    scope = {"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.4"}}
    with pytest.raises(OSError):  # noqa: PT011 - the injected disconnect
        await resp(scope, receive, send)
    assert not d.exists()


async def test_stale_download_temp_dirs_swept_on_next_download(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    import os

    stale = tmp_dirs.data_dir / "tmp" / "old"
    stale.mkdir(parents=True)
    (stale / "big.NEF").write_bytes(b"x")
    os.utime(stale, (1, 1))
    await _shoot(connected_client, app, "JPEG Fine")
    name = (await connected_client.get(F, params={"folder": CARD_FOLDER})).json()["items"][0][
        "name"
    ]
    assert (await connected_client.get(f"{F}{CARD_FOLDER}/{name}")).status_code == 200
    assert not stale.exists()
