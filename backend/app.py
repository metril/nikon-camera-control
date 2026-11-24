"""Application factory. All configuration comes from the config file, never the environment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api.errors import install_error_handlers
from backend.api.origin import OriginGuardMiddleware
from backend.api.v1 import api_router
from backend.api.v1.sessions import build_sessions_service
from backend.camera.backend import CameraBackend
from backend.core import paths
from backend.core.camera_service import CameraService
from backend.core.config_store import AppConfig, ConfigStore
from backend.core.events import EventBus
from backend.core.jobs import JobManager, JobStatus
from backend.core.registry import ServiceRegistry
from backend.core.secrets import SecretStore
from backend.core.state import CameraState
from backend.services.backup import BackupService
from backend.services.locations import LocationService
from backend.services.storage import cleanup_stale

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
JOB_SHUTDOWN_WAIT_S = 20.0


def _default_backend_factory(store: ConfigStore) -> Callable[[], CameraBackend]:
    def factory() -> CameraBackend:
        # re-read on every connect so toggling "Demo camera" applies on the next connect
        if store.config.demo_camera:
            from backend.camera.fake import FakeCamera

            return FakeCamera(emit_capture_complete=True)
        from backend.camera.gphoto2_backend import Gphoto2Backend

        return Gphoto2Backend()

    return factory


def _install_spa(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    # All methods: an unknown /api path must give the 404 envelope, not 405.
    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def spa(request: Request, path: str) -> Response:
        head = path.split("/", 1)[0]
        if request.method not in ("GET", "HEAD") or head in ("api", "docs", "openapi.json"):
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
    target_dir: Path | None = None,
    location_options: dict[str, Any] | None = None,
    backend_factory: Callable[[], CameraBackend] | None = None,
    frontend_dist: Path | None = None,
    auto_connect: bool = True,
    event_quiet_window_s: float | None = None,
    disconnect_wait_s: float | None = None,
) -> FastAPI:
    """Build the app. ``frontend_dist`` None means no SPA is served.

    ``target_dir`` pins a fixed storage target (tests, tools): no mounting, no hashing, no backups.
    ``location_options`` are extra ``LocationService`` arguments (fake runner, mount paths, ...).
    ``auto_connect`` starts a background connect attempt at startup (failures are logged).
    ``event_quiet_window_s`` / ``disconnect_wait_s`` override CameraService tuning (tests);
    the quiet window otherwise comes from ``config.camera.event_quiet_window_s``.
    """
    data = data_dir if data_dir is not None else paths.DATA_DIR
    store = config_store if config_store is not None else ConfigStore(data / "config.json")
    factory = backend_factory if backend_factory is not None else _default_backend_factory(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        if not store.config.demo_camera:
            from backend.camera.gphoto2_backend import library_version

            log.info("libgphoto2 version %s", library_version())
        bus = EventBus()
        bus.bind_loop(loop)
        jobs = JobManager(bus)
        service = CameraService(
            factory,
            store,
            bus,
            event_quiet_window_s=event_quiet_window_s,  # None: read live from the config
            **({"disconnect_wait_s": disconnect_wait_s} if disconnect_wait_s is not None else {}),
        )
        app.state.event_bus = bus
        app.state.job_manager = jobs
        app.state.camera_service = service
        registry = ServiceRegistry()
        app.state.services = registry

        def busy() -> bool:
            if service.state in (
                CameraState.CAPTURING,
                CameraState.RECORDING,
                CameraState.BULB,
            ):
                return True
            if any(
                j.kind != "verify" and j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                for j in jobs.list()
            ):
                return True
            tl = registry.peek("timelapse")
            return tl is not None and tl.status().state in ("running", "paused", "stopping")

        locations = LocationService(
            store,
            SecretStore(data / "secrets.json"),
            bus,
            busy=busy,
            fixed_target=target_dir,
            **(location_options or {}),
        )
        backup = BackupService(store, bus, locations.source, locations.destinations)
        locations.on_stored = backup.trigger
        app.state.storage = locations
        app.state.backup = backup
        registry.get("locations", lambda: locations)
        registry.get("backup", lambda: backup)

        def housekeep() -> None:
            """Blocking: clean the target's caches and recover interrupted sessions."""
            try:
                root = locations.root()
            except Exception:
                return
            cleanup_stale(locations.cache(), root)
            if (root / "sessions").is_dir():  # nothing to recover otherwise
                sessions = registry.get("sessions", lambda: build_sessions_service(app.state))
                sessions.recover_interrupted()

        async def run_housekeeping() -> None:
            try:
                await asyncio.to_thread(housekeep)
            except Exception:
                log.exception("startup cleanup failed")

        housekept: list[tuple[str, int] | None] = [None]

        def start_housekeeping() -> None:
            """Once per target change / new mount of the target, and never while busy."""
            key = locations.housekeeping_key()
            if key is None or key == housekept[0] or busy():
                return
            housekept[0] = key
            loop.create_task(run_housekeeping(), name="storage-housekeeping")

        def on_location(reason: str, location_id: str | None) -> None:
            if reason == "mounted" and location_id != locations.target_id:
                backup.trigger()  # a backup (or any location) came online
            if reason in ("mounted", "target") and location_id == locations.target_id:
                start_housekeeping()
                backup.trigger()

        locations.subscribe(on_location)
        backup.start()
        await locations.start()
        if target_dir is not None:
            await run_housekeeping()
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
            # Jobs first (bulb must close the shutter, brackets restore settings, focus returns):
            # they need the camera. Bounded so cleanup can run but shutdown cannot hang.
            try:
                await jobs.shutdown(wait_s=JOB_SHUTDOWN_WAIT_S)
            except Exception:
                log.exception("job shutdown failed")
            await registry.aclose()
            await service.stop()
            bus.close()

    app = FastAPI(
        title="Nikon Camera Control",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.config_store = store
    app.state.started_at = datetime.now(UTC)
    app.state.data_dir = data

    # Added before install_error_handlers so the request-id middleware stays outermost.
    app.add_middleware(OriginGuardMiddleware, config_store=store)
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
