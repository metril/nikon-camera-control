from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.api.v1 import kiosk
from backend.core.config_store import ConfigStore

URL = "/api/v1/kiosk/scale"


class Stream:
    """Drive the ASGI app directly: httpx buffers whole bodies, so it can't read an open stream."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.chunks: asyncio.Queue[str] = asyncio.Queue()
        self.disconnect = asyncio.Event()
        self.headers: dict[str, str] = {}
        self.status = 0
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": URL, "raw_path": URL.encode(), "query_string": b"", "headers": [],
            "server": ("t", 80), "client": ("c", 1), "scheme": "http", "root_path": "",
        }  # fmt: skip

        async def receive() -> dict[str, Any]:
            await self.disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(msg: dict[str, Any]) -> None:
            if msg["type"] == "http.response.start":
                self.status = msg["status"]
                self.headers = {k.decode(): v.decode() for k, v in msg["headers"]}
            elif msg["type"] == "http.response.body" and msg.get("body"):
                await self.chunks.put(msg["body"].decode())

        self.task = asyncio.create_task(self.app(scope, receive, send))  # type: ignore[arg-type]

    async def next_data(self) -> str:
        while True:
            chunk = await asyncio.wait_for(self.chunks.get(), 5)
            if chunk.startswith("data: "):
                return chunk.removeprefix("data: ").strip()


async def test_stream_open_sends_current_then_changes(
    app: FastAPI, client: httpx.AsyncClient, config_store: ConfigStore
) -> None:
    await client.post("/api/v1/config/api-key")  # auth on: the stream stays open
    s = Stream(app)
    await s.start()
    assert await s.next_data() == "auto"
    assert s.status == 200 and s.headers["content-type"].startswith("text/event-stream")
    config_store.update({"kiosk": {"scale": "1.5"}})
    assert await s.next_data() == "1.5"
    config_store.update({"liveview": {"target_fps": 9}})  # unrelated change: no event
    config_store.update({"kiosk": {"scale": "2"}})
    assert await s.next_data() == "2"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)


async def test_subscriber_removed_on_disconnect(
    app: FastAPI, client: httpx.AsyncClient, config_store: ConfigStore
) -> None:
    before = len(config_store._subscribers)
    s = Stream(app)
    await s.start()
    await s.next_data()
    assert len(config_store._subscribers) == before + 1
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)
    assert len(config_store._subscribers) == before


async def test_invalid_scale_rejected(client: httpx.AsyncClient) -> None:
    r = await client.patch("/api/v1/config", json={"kiosk": {"scale": "3"}})
    assert r.status_code in (400, 422)


async def test_idle_stream_sends_ping(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kiosk, "PING_INTERVAL_S", 0.05)
    s = Stream(app)
    await s.start()
    assert await s.next_data() == "auto"
    assert await asyncio.wait_for(s.chunks.get(), 5) == ": ping\n\n"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)
