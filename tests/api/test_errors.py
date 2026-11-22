from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from backend.core.errors import CameraBusy


class Body(BaseModel):
    n: int


def _shape(r: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status
    err: dict[str, Any] = r.json()["error"]
    assert set(err) == {"code", "message", "details", "request_id"}
    assert err["code"] == code
    assert err["request_id"] == r.headers["x-request-id"]
    return err


async def test_app_error(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/busy")
    async def busy() -> None:
        raise CameraBusy(details={"x": 1})

    err = _shape(await client.get("/busy"), 409, "CAMERA_BUSY")
    assert err["details"] == {"x": 1}


async def test_not_found_and_method(client: httpx.AsyncClient) -> None:
    _shape(await client.get("/nope"), 404, "NOT_FOUND")
    _shape(await client.delete("/api/v1/config/schema"), 405, "METHOD_NOT_ALLOWED")


async def test_validation(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.post("/v")
    async def v(b: Body) -> None: ...

    err = _shape(await client.post("/v", json={"n": "x"}), 422, "VALIDATION_ERROR")
    assert err["details"]["errors"][0]["loc"] == ["body", "n"]


async def test_unhandled_hides_internals(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    r = await client.get("/boom")
    err = _shape(r, 500, "INTERNAL")
    assert "secret" not in r.text and err["message"] == "Internal server error"


async def test_request_ids_unique(client: httpx.AsyncClient) -> None:
    a = await client.get("/api/v1/config")
    b = await client.get("/api/v1/config")
    assert a.headers["x-request-id"] != b.headers["x-request-id"]
    assert len(a.headers["x-request-id"]) == 32
