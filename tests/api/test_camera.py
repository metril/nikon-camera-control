import httpx
from fastapi import FastAPI

C = "/api/v1/camera"


async def test_status_disconnected(client: httpx.AsyncClient) -> None:
    r = await client.get(C)
    assert r.status_code == 200
    assert r.json()["state"] == "disconnected" and r.json()["connected"] is False
    assert r.json()["model"] is None


async def test_connect_disconnect(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{C}/connect")
    body = r.json()
    assert r.status_code == 200 and body["state"] == "idle" and body["connected"] is True
    assert body["model"] == "Nikon DSC D500" and body["serial"] == "9000001"
    assert body["connected_at"] and body["last_activity"]
    assert (await client.post(f"{C}/connect")).status_code == 200  # idempotent
    r = await client.post(f"{C}/disconnect")
    assert r.json()["state"] == "disconnected"


async def test_connect_failure_envelope(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.camera_service._factory().unplug()
    r = await client.post(f"{C}/connect")
    assert r.status_code == 404 and r.json()["error"]["code"] == "CAMERA_NOT_FOUND"
    assert (await client.get(C)).json()["state"] == "disconnected"
    assert "switched on" in r.json()["error"]["message"]


async def test_connect_while_off_connects_once_camera_appears(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    import asyncio

    fake = app.state.camera_service._factory()
    fake.unplug()
    assert (await client.post(f"{C}/connect")).status_code == 404
    await asyncio.sleep(1.5)
    fake.replug()
    for _ in range(80):
        if (await client.get(C)).json()["connected"]:
            break
        await asyncio.sleep(0.1)
    assert (await client.get(C)).json()["connected"] is True


async def test_not_connected_errors(client: httpx.AsyncClient) -> None:
    for path in ("battery", "storage", "summary"):
        r = await client.get(f"{C}/{path}")
        assert r.status_code == 503 and r.json()["error"]["code"] == "CAMERA_NOT_CONNECTED", path


async def test_battery_storage_summary(connected_client: httpx.AsyncClient) -> None:
    r = await connected_client.get(f"{C}/battery")
    assert r.json() == {"level": "87%", "percent": 87}
    r = await connected_client.get(f"{C}/storage")
    assert r.json()["cards"][0]["access"] == "rw"
    r = await connected_client.get(f"{C}/summary")
    assert "D500" in r.json()["summary"]


async def test_lease_owner_reported(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    async with app.state.camera_service.lease("timelapse"):
        assert (await connected_client.get(C)).json()["leased_by"] == "timelapse"
        r = await connected_client.get(f"{C}/summary")
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"


async def test_requires_api_key(client: httpx.AsyncClient) -> None:
    key = (await client.post("/api/v1/config/api-key")).json()["api_key"]
    assert (await client.get(C)).status_code == 401
    assert (await client.get(C, headers={"X-API-Key": key})).status_code == 200


async def test_demo_toggle_disconnects(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    import asyncio

    r = await connected_client.patch("/api/v1/config", json={"demo_camera": False})
    assert r.status_code == 200
    for _ in range(50):
        if app.state.camera_service.state == "disconnected":
            break
        await asyncio.sleep(0.05)
    assert app.state.camera_service.state == "disconnected"
