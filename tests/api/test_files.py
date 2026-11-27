import asyncio
import io
import os
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

import backend.services.files as files_mod

F = "/api/v1/files"
T = "/api/v1/thumbnails"


def _jpg(p: Path, size: tuple[int, int] = (640, 480)) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 120, 200)).save(p, "JPEG")


def _out(app: FastAPI) -> Path:
    return app.state.storage.root()


async def test_list_recursive_with_folders_and_filters(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    o = _out(app)
    _jpg(o / "a.jpg")
    _jpg(o / "sess1" / "b.jpg")
    _jpg(o / "sess1" / "deep" / "c.jpg")
    (o / "sess1" / "r.NEF").write_bytes(b"x")
    (o / "x.jpg.part").write_bytes(b"x")
    (o / ".hidden").mkdir()
    (o / ".hidden" / "h.jpg").write_bytes(b"x")
    body = (await client.get(F)).json()
    assert body["total"] == 4  # session files are listed; .part and dot dirs hidden
    assert [f["path"] for f in body["folders"]] == ["sess1"]
    assert {f["path"] for f in body["items"]} == {
        "a.jpg",
        "sess1/b.jpg",
        "sess1/deep/c.jpg",
        "sess1/r.NEF",
    }
    sub = (await client.get(F, params={"folder": "sess1", "kind": "raw"})).json()
    assert [f["name"] for f in sub["items"]] == ["r.NEF"]
    assert sub["items"][0]["has_thumbnail"] is True
    sub = (await client.get(F, params={"folder": "sess1"})).json()
    assert [f["path"] for f in sub["folders"]] == ["sess1/deep"] and sub["total"] == 3
    paged = (await client.get(F, params={"limit": 2, "page": 2, "sort": "name"})).json()
    assert len(paged["items"]) == 2 and paged["total"] == 4


async def test_listing_picks_up_external_changes_and_uses_cache(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch
) -> None:
    o = _out(app)
    _jpg(o / "a.jpg")
    assert (await client.get(F)).json()["total"] == 1
    scans = 0
    idx = app.state.services.get("files", lambda: None).index
    orig = idx._scan

    def counting() -> None:
        nonlocal scans
        scans += 1
        orig()

    monkeypatch.setattr(idx, "_scan", counting)
    await client.get(F)
    await client.get(F)
    assert scans == 0  # cache hit: no rescan
    _jpg(o / "b.jpg")
    assert (await client.get(F)).json()["total"] == 2
    assert scans == 1


async def test_list_missing_folder_and_traversal(app: FastAPI, client: httpx.AsyncClient) -> None:
    assert (await client.get(F, params={"folder": "nope"})).status_code == 404
    r = await client.get(F, params={"folder": "../.."})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_NOT_ALLOWED"


async def test_download_and_delete(app: FastAPI, client: httpx.AsyncClient) -> None:
    o = _out(app)
    _jpg(o / "s" / "a.jpg")
    r = await client.get(f"{F}/s/a.jpg")
    assert r.status_code == 200 and r.content == (o / "s" / "a.jpg").read_bytes()
    assert (await client.delete(f"{F}/s/a.jpg")).json() == {"ok": True}
    assert not (o / "s" / "a.jpg").exists()
    assert (await client.get(F)).json()["total"] == 0
    r = await client.delete(f"{F}/s/a.jpg")
    assert r.status_code == 404 and r.json()["error"]["code"] == "FILE_NOT_FOUND"


async def test_delete_dotdot_is_400_not_500(app: FastAPI, client: httpx.AsyncClient) -> None:
    r = await client.delete(f"{F}/..")
    assert r.status_code in (400, 404)
    r = await client.delete(f"{F}/%2e%2e")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_NOT_ALLOWED"
    r = await client.delete(f"{F}/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert r.status_code == 400
    r = await client.get(f"{F}/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert r.status_code == 400
    r = await client.get(f"{F}/%2fetc%2fpasswd")
    assert r.status_code == 400


async def test_symlink_escape_blocked(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    os.symlink(tmp_path, _out(app) / "link")
    r = await client.get(f"{F}/link/secret.txt")
    assert r.status_code == 400
    assert secret.exists()


async def test_delete_folder_refused(app: FastAPI, client: httpx.AsyncClient) -> None:
    _jpg(_out(app) / "sess" / "a.jpg")
    r = await client.delete(f"{F}/sess")
    assert r.status_code == 400
    assert (_out(app) / "sess" / "a.jpg").exists()


async def test_thumbnail_is_small_jpeg_not_original(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    o = _out(app)
    _jpg(o / "s" / "a.jpg", (2000, 1500))
    r = await client.get(f"{T}/s/a.jpg", params={"size": 100})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert len(r.content) < (o / "s" / "a.jpg").stat().st_size
    from io import BytesIO

    assert max(Image.open(BytesIO(r.content)).size) == 100
    assert (await client.get(f"{T}/s/a.jpg", params={"size": 10})).status_code == 422
    assert (await client.get(f"{T}/s/a.jpg", params={"size": 5000})).status_code == 422
    assert list((app.state.storage.cache() / "thumbs").glob("*.jpg"))


async def test_thumbnail_unsupported_415(app: FastAPI, client: httpx.AsyncClient) -> None:
    (_out(app) / "a.mov").write_bytes(b"x")
    r = await client.get(f"{T}/a.mov")
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA"
    assert (await client.get(f"{T}/nope.jpg")).status_code == 404


async def test_openapi_operation_ids(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    assert paths["/api/v1/files"]["get"]["operationId"] == "list_files"
    assert paths["/api/v1/thumbnails/{path}"]["get"]["operationId"] == "get_thumbnail"
    assert paths["/api/v1/files/{path}"]["delete"]["operationId"] == "delete_file"


async def test_file_named_thumbnail_is_downloadable_not_shadowed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    (_out(app) / "a.jpg").mkdir()
    (_out(app) / "a.jpg" / "thumbnail").write_bytes(b"raw-bytes")
    r = await client.get(f"{F}/a.jpg/thumbnail")
    assert r.status_code == 200
    assert r.content == b"raw-bytes"


async def test_nested_paths_with_encoded_slashes_resolve(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    # the generated client percent-encodes the whole path, slashes included (%2F)
    _jpg(_out(app) / "sessions" / "s1" / "deep" / "f.jpg")
    for enc in ("sessions/s1/deep/f.jpg", "sessions%2Fs1%2Fdeep%2Ff.jpg"):
        assert (await client.get(f"{F}/{enc}")).status_code == 200
        r = await client.get(f"{T}/{enc}", params={"size": 128})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert (await client.delete(f"{F}/sessions%2Fs1%2Fdeep%2Ff.jpg")).status_code == 200
    assert (await client.get(f"{F}/sessions%2Fs1%2Fdeep%2Ff.jpg")).status_code == 404


# ---- bulk delete and ZIP downloads ---------------------------------------------------------
async def test_bulk_delete_partial_failure_and_traversal(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    o = _out(app)
    _jpg(o / "a.jpg")
    _jpg(o / "d" / "b.jpg")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    r = await client.post(
        f"{F}/delete",
        json={"paths": ["a.jpg", "nope.jpg", "d", "../outside.txt", "/etc/passwd", "d/b.jpg"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == ["a.jpg", "d/b.jpg"]
    assert {f["path"] for f in body["failed"]} == {"nope.jpg", "d", "../outside.txt", "/etc/passwd"}
    assert outside.exists() and (o / "d").is_dir() and not (o / "a.jpg").exists()
    assert (await client.get(F)).json()["total"] == 0  # index invalidated
    assert (await client.post(f"{F}/delete", json={"paths": []})).status_code == 422


async def test_zip_contents_and_ticket_is_single_use(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    o = _out(app)
    _jpg(o / "a.jpg")
    _jpg(o / "s" / "a.jpg")
    (o / "s" / "big.bin").write_bytes(os.urandom(3 * 1024 * 1024))
    paths = ["a.jpg", "s/a.jpg", "s/big.bin", "a.jpg"]
    r = await client.post(f"{F}/zip", json={"paths": paths})
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith("/api/v1/files/zip/")
    got = await client.get(url)
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    assert "attachment" in got.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(got.content)) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == ["a.jpg", "s/a.jpg", "s/big.bin"]  # deduped, folders kept
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
        assert zf.read("s/big.bin") == (o / "s" / "big.bin").read_bytes()
        assert zf.read("a.jpg") == (o / "a.jpg").read_bytes()
    assert (await client.get(url)).status_code == 404  # single use


async def test_zip_single_path_streams_the_file_itself(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    o = _out(app)
    _jpg(o / "s" / "one.jpg")
    url = (await client.post(f"{F}/zip", json={"paths": ["s/one.jpg"]})).json()["url"]
    got = await client.get(url)
    assert got.content == (o / "s" / "one.jpg").read_bytes()
    assert "one.jpg" in got.headers["content-disposition"]
    assert (await client.get(url)).status_code == 404


@pytest.mark.parametrize("bad", ["../x.jpg", "/etc/passwd", "a/../../x", ".hidden", "x.jpg.part"])
async def test_zip_rejects_bad_paths(app: FastAPI, client: httpx.AsyncClient, bad: str) -> None:
    _jpg(_out(app) / "a.jpg")
    r = await client.post(f"{F}/zip", json={"paths": ["a.jpg", bad]})
    assert r.status_code == 400


async def test_zip_missing_file_is_404_and_ticket_expires(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _jpg(_out(app) / "a.jpg")
    assert (await client.post(f"{F}/zip", json={"paths": ["a.jpg", "gone.jpg"]})).status_code == 404
    url = (await client.post(f"{F}/zip", json={"paths": ["a.jpg"]})).json()["url"]
    real = files_mod.time.monotonic
    monkeypatch.setattr(
        files_mod.time, "monotonic", lambda: real() + files_mod.ZIP_TICKET_TTL_S + 1
    )
    assert (await client.get(url)).status_code == 404
    assert (await client.get(f"{F}/zip/not-a-ticket")).status_code == 404


async def test_zip_stream_worker_stops_when_client_goes_away(tmp_path: Path) -> None:
    import threading

    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (32 * 1024 * 1024))  # far more than the queue can buffer
    gen = files_mod.FileService.stream_zip([(big, "big.bin")])
    assert await anext(gen)
    await gen.aclose()
    for _ in range(100):
        if not [t for t in threading.enumerate() if t.name == "zip-stream"]:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("zip worker thread kept running")


async def test_zip_stream_abort_wakes_blocked_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that leaves while the consumer thread waits in q.get must not leak it."""
    seen: dict = {}

    def silent_worker(items, q, cancel):  # produces nothing, so q.get blocks
        seen["q"] = q
        cancel.wait(10)

    monkeypatch.setattr(files_mod, "_zip_worker", silent_worker)
    gen = files_mod.FileService.stream_zip([])
    task = asyncio.ensure_future(anext(gen))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):  # _END was posted and then consumed by the blocked get
        if seen["q"].empty():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("consumer thread was never woken")


async def test_zip_ticket_refused_after_target_change(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        _jpg(d / "x.jpg")
        _jpg(d / "y.jpg")

    from backend.core.storage_root import FixedRoot

    store = FixedRoot(a)
    svc = files_mod.FileService(store)
    ticket = svc.create_zip_ticket(["x.jpg", "y.jpg"])
    store._root = b  # target switched to another location with the same file names
    with pytest.raises(files_mod.FileNotFoundError_):
        svc.redeem_zip_ticket(ticket)
    store._root = a
    ticket = svc.create_zip_ticket(["x.jpg", "y.jpg"])
    assert len(svc.redeem_zip_ticket(ticket).items) == 2
