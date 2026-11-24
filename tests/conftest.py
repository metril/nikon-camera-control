"""Shared pytest configuration and fixtures (xdist-safe: tmp_path only, no ports)."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.app import create_app
from backend.camera.fake import FakeCamera
from backend.core.config_store import AppConfig, ConfigStore


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-camera", action="store_true", default=False, help="run tests marked 'hardware'"
    )


def _find_ffmpeg() -> str | None:
    """System ffmpeg first, else the imageio-ffmpeg bundled binary, else None."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


@pytest.fixture(scope="session")
def ffmpeg_exe() -> str:
    exe = _find_ffmpeg()
    if exe is None:
        pytest.skip("ffmpeg not available (system or imageio-ffmpeg)")
    return exe


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_hw = pytest.mark.skip(reason="needs a physical camera (--real-camera)")
    skip_ff = pytest.mark.skip(reason="ffmpeg not installed")
    have_hw = config.getoption("--real-camera")
    have_ff = _find_ffmpeg() is not None
    for item in items:
        if "hardware" in item.keywords and not have_hw:
            item.add_marker(skip_hw)
        if "ffmpeg" in item.keywords and not have_ff:
            item.add_marker(skip_ff)


@dataclass(frozen=True)
class TmpDirs:
    data_dir: Path
    output_dir: Path


@pytest.fixture
def fake_camera() -> FakeCamera:
    return FakeCamera()


@pytest.fixture
def tmp_dirs(tmp_path: Path) -> TmpDirs:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    return TmpDirs(data_dir, output_dir)


@pytest.fixture
def app_config() -> AppConfig:
    """Defaults tuned for fast tests (short timeouts, demo camera on)."""
    return AppConfig.model_validate(
        {
            "camera": {
                "keepalive_interval_s": 5.0,
                "connect_timeout_s": 1.0,
                "connect_retries": 1,
                "reconnect_interval_s": 0.5,
            },
            "timelapse": {"min_interval_s": 0.1},
            "demo_camera": True,
        }
    )


@pytest.fixture
def config_store(tmp_dirs: TmpDirs, app_config: AppConfig) -> ConfigStore:
    return ConfigStore(tmp_dirs.data_dir / "config.json", initial=app_config)


@pytest.fixture
def app(tmp_dirs: TmpDirs, config_store: ConfigStore, fake_camera: FakeCamera) -> FastAPI:
    """Real app (all routers) over tmp dirs and the test's FakeCamera; no auto-connect."""
    return create_app(
        config_store=config_store,
        data_dir=tmp_dirs.data_dir,
        target_dir=tmp_dirs.output_dir,
        backend_factory=lambda: fake_camera,
        auto_connect=False,
        event_quiet_window_s=0.02,
        disconnect_wait_s=0.5,
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """httpx client with the app lifespan running (services on ``app.state``)."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


@pytest.fixture
async def connected_client(app: FastAPI, client: httpx.AsyncClient) -> httpx.AsyncClient:
    """``client`` with the fake camera already connected."""
    await app.state.camera_service.connect()
    return client


@pytest.fixture
def ws_client(app: FastAPI) -> Iterator[TestClient]:
    """Starlette TestClient (lifespan running) for WebSocket tests; use
    ``with ws_client.websocket_connect(url) as ws``. Sync tests only."""
    with TestClient(app) as tc:
        yield tc


@pytest.fixture(autouse=True)
def _no_leaked_threads() -> Iterator[None]:
    """Every test must stop the threads it started (camera workers, test-client portals)."""
    before = set(threading.enumerate())
    yield
    deadline = time.monotonic() + 3.0
    while True:
        leaked = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        if not leaked or time.monotonic() > deadline:
            break
        time.sleep(0.02)
    assert not leaked, f"leaked threads: {[t.name for t in leaked]}"
