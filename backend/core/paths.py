"""Fixed filesystem locations (container layout). Classes take paths as arguments."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTAINER_ROOT = Path("/app")


def _pick(name: str) -> Path:
    if _CONTAINER_ROOT.exists():
        return _CONTAINER_ROOT / name
    return REPO_ROOT / name


DATA_DIR: Path = _pick("data")
CONFIG_FILE: Path = DATA_DIR / "config.json"
