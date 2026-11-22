"""ASGI entry point: ``uvicorn backend.asgi:create --factory``."""

from __future__ import annotations

from fastapi import FastAPI

from backend.app import create_app
from backend.core.paths import REPO_ROOT


def create() -> FastAPI:
    return create_app(frontend_dist=REPO_ROOT / "frontend" / "dist")
