import httpx
from fastapi import FastAPI

from backend import __version__
from backend.core.state import CameraState


async def test_health_open_even_with_api_key(app: FastAPI, client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/config/api-key")
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "camera_connected": False,
        "camera_state": "disconnected",
        "version": __version__,
    }
    assert (await client.get("/api/v1/info")).status_code == 401


async def test_health_degraded_on_error(app: FastAPI, client: httpx.AsyncClient) -> None:
    await app.state.camera_service.transition(CameraState.ERROR)
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "degraded"


async def test_info(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/info")
    body = r.json()
    assert r.status_code == 200
    assert body["backend"] == "demo" and body["auth_enabled"] is False
    assert body["output_free_bytes"] > 0 and isinstance(body["ffmpeg_available"], bool)


async def test_info_started_at_is_utc_and_stable(client: httpx.AsyncClient) -> None:
    from datetime import UTC, datetime, timedelta

    a = (await client.get("/api/v1/info")).json()["started_at"]
    t = datetime.fromisoformat(a)
    assert t.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - t).total_seconds()) < 60
    assert (await client.get("/api/v1/info")).json()["started_at"] == a


async def test_openapi_metadata(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["info"]["version"] == __version__
    ids = [op["operationId"] for p in spec["paths"].values() for op in p.values()]
    assert len(ids) == len(set(ids)) and all(i == i.lower() for i in ids)
    assert {"get_health", "get_info", "get_camera", "connect_camera", "get_camera_summary"} <= set(
        ids
    )
    assert (await client.get("/docs")).status_code == 200
