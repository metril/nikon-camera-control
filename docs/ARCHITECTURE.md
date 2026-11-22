# Architecture

Browser <-> FastAPI (`/api/v1`, REST + two WebSockets) <-> `CameraService` <-> camera backend <-> USB.
The backend also serves the built frontend (`frontend/dist`) at `/`.

## Layers

1. **Camera backend** (`backend/camera/backend.py`): a synchronous, blocking `CameraBackend` Protocol and the dataclasses it uses. Implementations: `gphoto2_backend.py` (python-gphoto2, the only module importing `gphoto2`; translates every gphoto2 error to a domain error in `backend/core/errors.py`) and `fake.py` (`FakeCamera`, used by the demo camera switch and all tests).
2. **CameraService** (`backend/core/camera_service.py`): the single owner of the camera. One worker thread executes a priority queue of calls (control > capture > keepalive > live view), so PTP operations never overlap. A state machine (`state.py`: disconnected/idle/liveview/capturing/recording/bulb/busy/error) gates what is allowed. `lease(owner)` gives a long operation (time-lapse, bulb, focus stack, recording) exclusive control. Keepalive and reconnect run as asyncio tasks; a per-connection settings cache serves reads. Capture drains camera events until `CAPTURE_COMPLETE` or a quiet window.
3. **Event bus** (`backend/core/events.py`): thread-safe publish, per-subscriber queues; feeds `/api/v1/ws/events`.
4. **Job manager** (`backend/core/jobs.py`): long operations (downloads, time-lapse, renders, stacks) run as cancellable jobs with progress events.
5. **Feature services** (`backend/services/*`): settings, liveview, capture, bulb, focus, recording, time-lapse (`timelapse/`), presets, sessions, video, camera files, thumbnails, camera admin (clock, capture target). They only reach the camera through `CameraService.call` and are created lazily by `ServiceRegistry` (`core/registry.py`). Routers in `backend/api/v1/*.py` are auto-discovered by `backend/app.py`; request/response models live in `backend/api/schemas/`.
6. **Config and key stores** (`core/config_store.py`, `core/security.py`): `ConfigStore` persists `AppConfig` as `data/config.json` (atomic writes, validated merge updates, change subscriptions, restart-required reporting). `ApiKeyStore` keeps the key's sha256 in `data/api_key.json`; a missing file means open mode, an unreadable one fails closed. There are no environment variables.
7. **Generated API artifacts**: `scripts/gen_api.py` writes `openapi.json` and `docs/API.md`; `bun run gen:api` generates the frontend client in `frontend/src/api`. `tests/test_api_drift.py`, `make api-check` and CI fail when any of them is stale.
8. **Frontend** (`frontend/src`): Vue 3 with Pinia stores over the generated client. The event socket (`stores/events.js`, reconnecting) drives store updates, so views react to server-side changes (settings, jobs, camera state) without polling. Live view uses its own binary socket.

## Shutdown order (`lifespan` in `backend/app.py`)

1. Unsubscribe the config listener and cancel background tasks (so nothing new starts).
2. `JobManager.shutdown` (bounded): jobs still need the camera to clean up (bulb must close the shutter, brackets restore settings, focus returns, recording stops).
3. `ServiceRegistry.aclose`: feature services close in reverse creation order, while the camera still works.
4. `CameraService.stop`: disconnect, stop keepalive/reconnect, stop the worker thread (bounded wait).
5. `EventBus.close`, last, so every earlier step can still publish its final events.

The bounds keep a wedged camera from hanging container stop.
