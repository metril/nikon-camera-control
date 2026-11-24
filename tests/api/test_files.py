import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from PIL import Image

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
