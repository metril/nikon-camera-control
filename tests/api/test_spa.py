from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from backend.app import create_app
from backend.core.config_store import ConfigStore


@pytest.fixture
async def spa_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SPA</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_text("ico")
    (tmp_path / "web" / "secret.txt").write_text("TOPSECRET")
    app = create_app(
        config_store=ConfigStore(tmp_path / "data" / "config.json"),
        data_dir=tmp_path / "data",
        target_dir=tmp_path / "out",
        frontend_dist=dist,
        auto_connect=False,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def test_index_and_deep_links(spa_client: httpx.AsyncClient) -> None:
    for p in ("/", "/gallery", "/some/deep/route"):
        r = await spa_client.get(p)
        assert r.status_code == 200 and "SPA" in r.text, p


async def test_files_and_assets(spa_client: httpx.AsyncClient) -> None:
    assert (await spa_client.get("/assets/app.js")).text == "console.log(1)"
    assert (await spa_client.get("/favicon.ico")).text == "ico"
    assert (await spa_client.get("/assets/missing.js")).status_code == 404


async def test_unknown_api_paths_are_json_404(spa_client: httpx.AsyncClient) -> None:
    for p in ("/api/v1/nope", "/api/nope", "/api", "/docs/x"):
        r = await spa_client.get(p)
        assert r.status_code == 404, p
        assert r.json()["error"]["code"] == "NOT_FOUND" and "SPA" not in r.text
    assert (await spa_client.get("/docs")).status_code == 200
    assert (await spa_client.get("/api/v1/openapi.json")).status_code == 200


async def test_non_get_unknown_api_paths_are_json_404(spa_client: httpx.AsyncClient) -> None:
    for method, p in (("POST", "/api/v1/nope"), ("DELETE", "/api/nope"), ("PUT", "/api")):
        r = await spa_client.request(method, p)
        assert r.status_code == 404, (method, p)
        assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "path",
    [
        "/..%2fsecret.txt",
        "/%2e%2e%2fsecret.txt",
        "/..%2f..%2f..%2fetc/passwd",
        "/assets/..%2f..%2fsecret.txt",
        "/../secret.txt",
        "/%00",
    ],
)
async def test_no_traversal(spa_client: httpx.AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert "TOPSECRET" not in r.text and "root:" not in r.text
    assert r.status_code in (200, 400, 404)
