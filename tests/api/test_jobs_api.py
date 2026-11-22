import asyncio

import httpx
from fastapi import FastAPI

J = "/api/v1/jobs"


async def test_unknown_job(client: httpx.AsyncClient) -> None:
    for call in (client.get, client.delete):
        r = await call(f"{J}/nope")
        assert r.status_code == 404 and r.json()["error"]["code"] == "JOB_NOT_FOUND"


async def test_list_get_cancel(app: FastAPI, client: httpx.AsyncClient) -> None:
    jm = app.state.job_manager
    gate = asyncio.Event()

    async def blocker(ctx):
        await gate.wait()
        return {}

    async def quick(ctx):
        return {"x": 1}

    a = jm.submit("slow", blocker)
    b = jm.submit("fast", quick)
    await asyncio.sleep(0.02)
    r = await client.get(J)
    assert [j["id"] for j in r.json()] == [b.id, a.id] or {j["id"] for j in r.json()} == {
        a.id,
        b.id,
    }
    assert [j["id"] for j in (await client.get(J, params={"kind": "slow"})).json()] == [a.id]
    assert [j["id"] for j in (await client.get(J, params={"status": "completed"})).json()] == [b.id]
    assert (await client.get(J, params={"status": "bogus"})).status_code == 422
    g = (await client.get(f"{J}/{b.id}")).json()
    assert g["status"] == "completed" and g["result"] == {"x": 1} and g["progress"] == 1.0
    r = await client.delete(f"{J}/{a.id}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # cancelling a finished job is a no-op returning it
    assert (await client.delete(f"{J}/{b.id}")).json()["status"] == "completed"
