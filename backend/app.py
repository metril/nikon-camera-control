"""Application factory. All configuration comes from the config file, never the environment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api.errors import install_error_handlers
from backend.api.v1 import api_router
from backend.camera.backend import CameraBackend
from backend.core import paths
from backend.core.camera_service import CameraService
from backend.core.config_store import AppConfig, ConfigStore
from backend.core.events import EventBus
from backend.core.jobs import JobManager

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

TAGS_METADATA: list[dict[str, str]] = [
    {"name": "system", "description": "Health and server information"},
    {"name": "camera", "description": "Camera connection and status"},
    {"name": "config", "description": "Application configuration and API key"},
    {"name": "events", "description": "WebSocket event stream"},
]


def _default_backend_factory(store: ConfigStore) -> Callable[[], CameraBackend]:
    def factory() -> CameraBackend:
        # re-read on every connect so toggling "Demo camera" applies on the next connect
        if store.config.demo_camera:
            from backend.camera.fake import FakeCamera

            return FakeCamera()
        from backend.camera.gphoto2_backend import Gphoto2Backend

        return Gphoto2Backend()

    return factory


def _install_spa(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        head = path.split("/", 1)[0]
        if head in ("api", "docs", "openapi.json"):
            raise HTTPException(status_code=404)
        try:
            candidate = (root / path).resolve()
        except (OSError, ValueError):
            raise HTTPException(status_code=404) from None
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=404)
        if path and candidate.is_file():
            return FileResponse(candidate)
        if not index.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(
    *,
    config_store: ConfigStore | None = None,
    data_dir: Path | None = None,
    output_dir: Path | None = None,
    backend_factory: Callable[[], CameraBackend] | None = None,
    frontend_dist: Path | None = None,
    auto_connect: bool = True,
) -> FastAPI:
    """Build the app. ``frontend_dist`` None means no SPA is served.

    ``auto_connect`` starts a background connect attempt at startup (failures are logged).
    """
    data = data_dir if data_dir is not None else paths.DATA_DIR
    output = output_dir if output_dir is not None else paths.OUTPUT_DIR
    store = config_store if config_store is not None else ConfigStore(data / "config.json")
    factory = backend_factory if backend_factory is not None else _default_backend_factory(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        bus = EventBus()
        bus.bind_loop(loop)
        jobs = JobManager(bus)
        service = CameraService(factory, store, bus)
        app.state.event_bus = bus
        app.state.job_manager = jobs
        app.state.camera_service = service
        await service.start()
        bg: set[asyncio.Task[Any]] = set()

        def spawn(coro: Any, name: str) -> None:
            task = loop.create_task(coro, name=name)
            bg.add(task)
            task.add_done_callback(bg.discard)

        def on_config(new: AppConfig, old: AppConfig) -> None:
            if new.demo_camera != old.demo_camera:
                loop.call_soon_threadsafe(spawn, service.disconnect(), "demo-switch-disconnect")

        unsubscribe = store.subscribe(on_config)

        async def initial_connect() -> None:
            try:
                await service.connect()
            except Exception as exc:
                log.warning("initial camera connect failed: %s", exc)

        if auto_connect:
            spawn(initial_connect(), "initial-connect")
        try:
            yield
        finally:
            unsubscribe()
            for task in list(bg):
                task.cancel()
            await asyncio.gather(*bg, return_exceptions=True)
            await service.stop()
            await jobs.shutdown()
            bus.close()

    app = FastAPI(
        title="Nikon Camera Control",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
    )
    app.state.config_store = store
    app.state.data_dir = data
    app.state.output_dir = output

    install_error_handlers(app)
    origins = list(store.config.cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["X-API-Key", "Content-Type"],
            expose_headers=["X-Request-ID"],
        )
    app.include_router(api_router, prefix=API_PREFIX)
    if frontend_dist is not None and frontend_dist.is_dir():
        _install_spa(app, frontend_dist)
    return app


__all__ = ["create_app"]
