from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.api.errors import install_error_handlers
from backend.api.v1.config import router as config_router
from backend.core.config_store import ConfigStore


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def publish(self, type: Any, data: dict[str, Any] | None = None) -> None:
        self.events.append((type, data or {}))


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(config_router, prefix="/api/v1")
    app.state.config_store = ConfigStore(tmp_path / "config.json")
    app.state.event_bus = RecordingBus()
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
