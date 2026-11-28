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

    def __init__(self, app: FastAPI, url: str = URL) -> None:
        self.app = app
        self.url = url
        self.chunks: asyncio.Queue[str] = asyncio.Queue()
        self.disconnect = asyncio.Event()
        self.headers: dict[str, str] = {}
        self.status = 0
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": self.url, "raw_path": self.url.encode(), "query_string": b"", "headers": [],
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


DISPLAY = "/api/v1/kiosk/display"


async def test_default_sleep_is_five_minutes(config_store: ConfigStore) -> None:
    assert config_store.config.kiosk.sleep_after_min == 5


async def test_invalid_sleep_rejected(client: httpx.AsyncClient) -> None:
    for bad in (-1, 1441, "never", 1.5):
        r = await client.patch("/api/v1/config", json={"kiosk": {"sleep_after_min": bad}})
        assert r.status_code in (400, 422), bad
    for ok in (0, 1, 1440):
        r = await client.patch("/api/v1/config", json={"kiosk": {"sleep_after_min": ok}})
        assert r.status_code == 200, ok


async def test_display_stream_open_without_key_sends_state_and_pushes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    key = (await client.post("/api/v1/config/api-key")).json()["api_key"]  # auth on
    h = {"X-API-Key": key}
    s = Stream(app, DISPLAY)  # the stream stays open without a key
    await s.start()
    assert await s.next_data() == "on"
    assert s.status == 200 and s.headers["content-type"].startswith("text/event-stream")
    r = await client.post(DISPLAY, json={"on": False}, headers=h)
    assert r.status_code == 200 and r.json() == {"on": False}
    assert await s.next_data() == "off dim"
    await client.post(DISPLAY, json={"on": True}, headers=h)
    assert await s.next_data() == "on"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)
    late = Stream(app, DISPLAY)  # a new connection gets the current state
    await client.post(DISPLAY, json={"on": False}, headers=h)
    await late.start()
    assert await late.next_data() == "off dim"
    late.disconnect.set()
    assert late.task is not None
    await asyncio.wait_for(late.task, 20)


async def test_display_post_requires_key_when_set(client: httpx.AsyncClient) -> None:
    key = (await client.post("/api/v1/config/api-key")).json()["api_key"]
    assert (await client.post(DISPLAY, json={"on": False})).status_code == 401
    ok = await client.post(DISPLAY, json={"on": False}, headers={"X-API-Key": key})
    assert ok.status_code == 200


async def test_sleep_setting_off_pushes_on(
    app: FastAPI, client: httpx.AsyncClient, config_store: ConfigStore
) -> None:
    s = Stream(app, DISPLAY)
    await s.start()
    assert await s.next_data() == "on"
    await client.post(DISPLAY, json={"on": False})
    assert await s.next_data() == "off dim"
    config_store.update({"kiosk": {"sleep_after_min": 10}})  # not 0: no event
    config_store.update({"kiosk": {"sleep_after_min": 0}})
    assert await s.next_data() == "on"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)


async def test_display_stream_pings_and_unsubscribes(
    app: FastAPI, config_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kiosk, "PING_INTERVAL_S", 0.05)
    before = len(config_store._subscribers)
    s = Stream(app, DISPLAY)
    await s.start()
    assert await s.next_data() == "on"
    assert await asyncio.wait_for(s.chunks.get(), 5) == ": ping\n\n"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)
    assert len(config_store._subscribers) == before


async def test_default_sleep_mode_and_validation(
    config_store: ConfigStore, client: httpx.AsyncClient
) -> None:
    assert config_store.config.kiosk.sleep_mode == "dim"
    assert (
        await client.patch("/api/v1/config", json={"kiosk": {"sleep_mode": "x"}})
    ).status_code in (400, 422)
    for ok in ("black", "dim", "off"):
        r = await client.patch("/api/v1/config", json={"kiosk": {"sleep_mode": ok}})
        assert r.status_code == 200, ok


async def test_display_stream_carries_mode_and_reemits_when_changed_asleep(
    app: FastAPI, client: httpx.AsyncClient, config_store: ConfigStore
) -> None:
    config_store.update({"kiosk": {"sleep_mode": "black"}})
    s = Stream(app, DISPLAY)
    await s.start()
    assert await s.next_data() == "on"
    config_store.update({"kiosk": {"sleep_mode": "dim"}})  # awake: no event
    await client.post(DISPLAY, json={"on": False})
    assert await s.next_data() == "off dim"
    config_store.update({"kiosk": {"sleep_mode": "off"}})
    assert await s.next_data() == "off off"
    config_store.update({"kiosk": {"sleep_after_min": 0}})
    assert await s.next_data() == "on"
    s.disconnect.set()
    assert s.task is not None
    await asyncio.wait_for(s.task, 20)
