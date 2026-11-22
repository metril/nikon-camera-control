from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, WebSocket
from starlette.testclient import TestClient

from backend.api.deps import service_dep
from backend.api.v1 import api_router, build_router, discover_modules
from backend.core.registry import ServiceRegistry


def _make_pkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> Any:
    name = f"disc_{uuid.uuid4().hex}"
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for fname, body in files.items():
        (pkg / f"{fname}.py").write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    mod = importlib.import_module(name)
    return mod


def test_real_package_routes_present() -> None:
    app = FastAPI()
    app.include_router(api_router)
    paths = set(app.openapi()["paths"])
    assert any(p.endswith("/health") for p in paths)
    assert any("camera" in p for p in paths)


def test_discovers_router_and_ws_router_sorted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body_b = (
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.get('/bbb')\ndef b(): return 1\n"
    )
    body_a = (
        "from fastapi import APIRouter, WebSocket\nws_router = APIRouter()\n"
        "@ws_router.websocket('/aaa')\nasync def a(ws: WebSocket):\n    await ws.accept()\n"
        "other = 5\n"
    )
    pkg = _make_pkg(tmp_path, monkeypatch, {"b_mod": body_b, "a_mod": body_a})
    mods = discover_modules(pkg)
    assert [m.__name__.rsplit(".", 1)[1] for m in mods] == ["a_mod", "b_mod"]
    app = FastAPI()
    app.include_router(build_router(mods))
    with TestClient(app) as c:
        assert c.get("/bbb").json() == 1
        with c.websocket_connect("/aaa"):
            pass


def test_import_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = _make_pkg(tmp_path, monkeypatch, {"bad": "raise ImportError('nope')\n"})
    with pytest.raises(ImportError, match="nope"):
        discover_modules(pkg)


def test_service_dep_http_and_ws() -> None:
    class Svc:
        pass

    built: list[Svc] = []

    def factory(state: Any) -> Svc:
        assert state.marker == "m"
        s = Svc()
        built.append(s)
        return s

    dep = service_dep("demo", factory)
    router = APIRouter()

    @router.get("/h")
    def h(svc: Svc = Depends(dep)) -> dict[str, int]:
        return {"id": id(svc)}

    @router.websocket("/w")
    async def w(ws: WebSocket, svc: Svc = Depends(dep)) -> None:
        await ws.accept()
        await ws.send_json({"id": id(svc)})
        await ws.close()

    app = FastAPI()
    app.state.marker = "m"
    app.state.services = ServiceRegistry()
    app.include_router(router)
    with TestClient(app) as c:
        http_id = c.get("/h").json()["id"]
        with c.websocket_connect("/w") as ws:
            assert ws.receive_json()["id"] == http_id
    assert len(built) == 1
