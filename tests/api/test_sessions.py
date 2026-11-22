from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from backend.api.schemas.sessions import SessionFile, SessionFrame

S = "/api/v1/sessions"


def _frame(i: int) -> SessionFrame:
    return SessionFrame(
        index=i,
        captured_at=datetime.now(UTC),
        files=[SessionFile(path=f"{i}.jpg", kind="jpeg", size=1)],
        set_index=i,
    )


async def _make(app: FastAPI, client: httpx.AsyncClient, frames: int = 0) -> str:
    assert (await client.get(S)).status_code == 200  # builds the service
    store = app.state.services.get("sessions", lambda: None)
    m = await store.create("Night", {"k": 1}, 10)
    for i in range(frames):
        await store.add_frame(m.id, _frame(i))
    return m.id


async def test_list_detail_frames_pagination(app: FastAPI, client: httpx.AsyncClient) -> None:
    assert (await client.get(S)).json()["items"] == []
    sid = await _make(app, client, 5)
    body = (await client.get(S)).json()
    assert body["total"] == 1 and body["items"][0]["frames_captured"] == 5
    assert "frames" not in body["items"][0]
    d = (await client.get(f"{S}/{sid}")).json()
    assert d["config"] == {"k": 1} and d["videos"] == [] and "frames" not in d
    r = (await client.get(f"{S}/{sid}/frames", params={"page": 2, "limit": 2})).json()
    assert [f["index"] for f in r["items"]] == [2, 3] and r["total"] == 5 and r["page"] == 2


async def test_rename_and_delete(app: FastAPI, client: httpx.AsyncClient) -> None:
    sid = await _make(app, client)
    r = await client.patch(f"{S}/{sid}", json={"name": "  New  "})
    assert r.status_code == 200 and r.json()["name"] == "New"
    assert (await client.patch(f"{S}/{sid}", json={"name": " "})).status_code == 422
    store = app.state.services.get("sessions", lambda: None)
    await store.update(sid, status="running")
    r = await client.delete(f"{S}/{sid}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    await store.update(sid, status="stopped")
    assert (await client.delete(f"{S}/{sid}")).json() == {"ok": True}
    r = await client.get(f"{S}/{sid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_traversal_ids_rejected(client: httpx.AsyncClient) -> None:
    for bad in ("..", "%2e%2e", "%2e%2e%2f%2e%2e", "a%2fb", "x" * 300):
        r = await client.get(f"{S}/{bad}")
        assert r.status_code in (400, 404), bad
        r = await client.delete(f"{S}/{bad}")
        assert r.status_code in (400, 404, 405), bad
    r = await client.get(f"{S}/not-an-id")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_NOT_ALLOWED"


async def test_operation_ids(app: FastAPI) -> None:
    ops = {
        op["operationId"]
        for path, item in app.openapi()["paths"].items()
        if path.startswith(S)
        for op in item.values()
        if "sessions" in op.get("tags", [])
    }
    assert ops == {
        "list_sessions",
        "get_session",
        "list_session_frames",
        "rename_session",
        "delete_session",
    }


async def test_crashed_sessions_recovered_at_startup_off_the_request_path(app: FastAPI) -> None:
    from backend.api.v1.sessions import build_sessions_service
    from backend.services.sessions import SessionStore

    out = app.state.output_dir
    old = SessionStore(out, fsync=False)
    m = await old.create("crashed", {}, 5)
    await old.update(m.id, status="running")
    for i in range(3):
        await old.add_frame(m.id, _frame(i))
    await old.aclose()
    # building the service no longer scans sessions synchronously (it would block the loop)
    assert (await build_sessions_service(app.state).get(m.id)).status == "running"
    async with app.router.lifespan_context(app):  # startup hook recovers in a thread
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            d = (await c.get(f"{S}/{m.id}")).json()
    assert d["status"] == "interrupted" and d["frames_captured"] == 3
