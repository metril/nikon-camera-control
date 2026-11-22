"""Shared pytest configuration and fixtures (xdist-safe: tmp_path only, no ports)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.camera.fake import FakeCamera
from backend.core.config_store import AppConfig, ConfigStore


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-camera", action="store_true", default=False, help="run tests marked 'hardware'"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_hw = pytest.mark.skip(reason="needs a physical camera (--real-camera)")
    skip_ff = pytest.mark.skip(reason="ffmpeg not installed")
    have_hw = config.getoption("--real-camera")
    have_ff = shutil.which("ffmpeg") is not None
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
                "capture_timeout_s": 1.0,
            },
            "liveview": {"frame_timeout_s": 0.1},
            "timelapse": {"min_interval_s": 0.1},
            "demo_camera": True,
        }
    )


@pytest.fixture
def config_store(tmp_dirs: TmpDirs, app_config: AppConfig) -> ConfigStore:
    return ConfigStore(tmp_dirs.data_dir / "config.json", initial=app_config)


# --- PLACEHOLDER: `app` / `client` fixtures will be added here by the app-factory task. ---
