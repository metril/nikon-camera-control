from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.core.config_store import ConfigStore

U = "/api/v1/config"


async def test_get_and_patch(app: FastAPI, client: httpx.AsyncClient) -> None:
    r = await client.get(U)
    assert r.status_code == 200
    assert r.json()["api_key_set"] is False and "api_key_hash" not in r.json()

    r = await client.patch(U, json={"liveview": {"target_fps": 12}, "cors_origins": ["http://x"]})
    body = r.json()
    assert r.status_code == 200
    assert body["config"]["liveview"]["target_fps"] == 12
    assert body["config"]["liveview"]["quality"] == "medium"
    assert body["restart_required"] == ["cors_origins"]
    assert app.state.event_bus.events[-1][0] == "config_changed"
    assert app.state.config_store.config.liveview.target_fps == 12


async def test_patch_invalid(client: httpx.AsyncClient) -> None:
    r = await client.patch(U, json={"video": {"crf": 999}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONFIG_INVALID"
    r = await client.patch(U, json={"api_key_hash": "x"})
    assert r.status_code == 422


async def test_schema(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{U}/schema")
    js = r.json()["json_schema"]
    assert "api_key_hash" not in js["properties"]
    assert js["properties"]["api_key_set"]["readOnly"] is True
    assert "target_fps" in js["$defs"]["LiveViewConfig"]["properties"]


async def test_key_lifecycle(app: FastAPI, client: httpx.AsyncClient, tmp_path: Path) -> None:
    r = await client.post(f"{U}/api-key")
    key = r.json()["api_key"]
    assert r.json()["config"]["api_key_set"] is True
    stored = app.state.config_store.config.api_key_hash
    assert stored and stored not in r.text

    r = await client.get(U)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    assert (await client.get(U, headers={"X-API-Key": "bad"})).status_code == 401
    h = {"X-API-Key": key}
    r = await client.get(U, headers=h)
    assert r.status_code == 200 and key not in r.text and stored not in r.text

    r = await client.post(f"{U}/api-key", headers=h)  # rotate
    key2 = r.json()["api_key"]
    assert key2 != key
    assert (await client.get(U, headers=h)).status_code == 401
    h2 = {"X-API-Key": key2}

    # reset keeps the key
    assert (await client.post(f"{U}/reset", headers=h2)).json()["config"]["api_key_set"] is True
    assert (await client.get(U)).status_code == 401
    # persisted across a new store
    assert ConfigStore(tmp_path / "config.json").config.api_key_hash is not None

    assert (await client.delete(f"{U}/api-key")).status_code == 401
    r = await client.delete(f"{U}/api-key", headers=h2)
    assert r.status_code == 200 and r.json()["config"]["api_key_set"] is False
    assert (await client.get(U)).status_code == 200


async def test_hash_never_in_any_response(app: FastAPI, client: httpx.AsyncClient) -> None:
    await client.post(f"{U}/api-key")
    stored = app.state.config_store.config.api_key_hash
    app.state.config_store.set_api_key_hash(None)
    for r in (
        await client.get(U),
        await client.get(f"{U}/schema"),
        await client.patch(U, json={"demo_camera": True}),
        await client.post(f"{U}/reset"),
        await client.get(U, headers={"X-API-Key": "x"}),
    ):
        assert stored not in r.text and "api_key_hash" not in r.text


async def test_openapi(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    ids = {op["operationId"] for p in spec["paths"].values() for op in p.values()}
    assert {
        "get_config",
        "get_config_schema",
        "update_config",
        "reset_config",
        "create_api_key",
        "delete_api_key",
    } <= ids
    assert "APIKeyHeader" in spec["components"]["securitySchemes"]
    assert "ErrorResponse" in spec["components"]["schemas"]
