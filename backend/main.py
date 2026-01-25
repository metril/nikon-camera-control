"""
Nikon D500 Camera Control - FastAPI Application

Main entry point for the camera control web application.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.camera.controller import CameraController
from backend.camera.exceptions import CameraError, CameraNotFoundError
from backend.camera.timelapse import TimelapseHandler
from backend.config import settings

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer() if settings.server.log_format == "console"
        else structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global camera controller instance
camera_controller = CameraController()

# Global time-lapse handler (initialized after app starts)
timelapse_handler = None

# WebSocket connection manager for status updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global timelapse_handler

    logger.info(
        "application_starting",
        host=settings.server.host,
        port=settings.server.port,
    )

    # Register camera state change handler
    def on_state_change(old_state, new_state):
        asyncio.create_task(
            ws_manager.broadcast({
                "type": "camera_state",
                "old_state": old_state.name,
                "new_state": new_state.name,
                "timestamp": datetime.now().isoformat(),
            })
        )

    camera_controller.on_state_change(on_state_change)

    # Initialize time-lapse handler
    async def timelapse_capture_callback():
        """Capture callback for time-lapse."""
        from backend.camera.capture import CaptureHandler
        handler = CaptureHandler(
            camera_controller._camera,
            camera_controller._context,
            camera_controller._lock,
            camera_controller
        )
        return await handler.capture_photo(download=True)

    async def timelapse_settings_callback(setting_name: str, value: str) -> bool:
        """Settings callback for bracketing - changes camera settings."""
        from backend.camera.settings import CameraSettingsManager
        try:
            manager = CameraSettingsManager(
                camera_controller._camera,
                camera_controller._context,
                camera_controller._lock
            )
            await manager.set_setting(setting_name, value)
            return True
        except Exception as e:
            logger.warning("timelapse_setting_change_failed", setting=setting_name, value=value, error=str(e))
            return False

    async def timelapse_event_callback(event_type, data):
        """Event callback for time-lapse progress."""
        await ws_manager.broadcast({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })

    timelapse_handler = TimelapseHandler(
        capture_callback=timelapse_capture_callback,
        settings_callback=timelapse_settings_callback,
        event_callback=timelapse_event_callback
    )

    # Try to connect to camera on startup (non-blocking)
    try:
        await camera_controller.connect()
    except CameraNotFoundError:
        logger.warning("camera_not_found_at_startup")
    except CameraError as e:
        logger.warning("camera_connection_failed_at_startup", error=str(e))

    yield

    # Cleanup
    logger.info("application_shutting_down")
    if timelapse_handler and timelapse_handler.state.value == "running":
        await timelapse_handler.stop()
    await camera_controller.disconnect()


# Create FastAPI app
app = FastAPI(
    title="Nikon D500 Camera Control",
    description="Web-based control application for Nikon D500 camera via USB",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(CameraError)
async def camera_error_handler(request, exc: CameraError):
    """Handle all camera-related errors."""
    logger.error("camera_error", error=str(exc), recoverable=exc.recoverable)
    return JSONResponse(
        status_code=503 if exc.recoverable else 500,
        content={
            "error": type(exc).__name__,
            "message": exc.message,
            "recoverable": exc.recoverable,
        },
    )


# =============================================================================
# Include API Routes
# =============================================================================

from backend.api.routes import camera as camera_routes
from backend.api.routes import settings as settings_routes
from backend.api.routes import capture as capture_routes
from backend.api.routes import timelapse as timelapse_routes

app.include_router(camera_routes.router)
app.include_router(settings_routes.router)
app.include_router(capture_routes.router)
app.include_router(timelapse_routes.router)


# =============================================================================
# Health Endpoint
# =============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "camera_connected": camera_controller.is_connected,
    }


# =============================================================================
# WebSocket Endpoints
# =============================================================================

from backend.camera.live_view import LiveViewHandler
from backend.api.websocket.live_view import liveview_ws_handler


@app.websocket("/ws/liveview")
async def websocket_liveview(websocket: WebSocket):
    """
    WebSocket endpoint for live view streaming.

    Sends binary JPEG frames at 5-10 FPS.
    """
    if not camera_controller.is_connected:
        await websocket.close(code=1003, reason="Camera not connected")
        return

    # Initialize live view handler if needed
    if not liveview_ws_handler.live_view_handler:
        handler = LiveViewHandler(
            camera_controller._camera,
            camera_controller._context,
            camera_controller._lock,
            camera_controller
        )
        liveview_ws_handler.set_handler(handler)

    await liveview_ws_handler.handle_connection(websocket)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time camera events.

    Events sent:
    - camera_state: State changes
    - capture_complete: After photo capture
    - timelapse_progress: Time-lapse updates
    - error: Error notifications
    """
    await ws_manager.connect(websocket)

    # Send initial status
    try:
        status = await camera_controller.get_status()
        await websocket.send_json({
            "type": "initial_status",
            "data": status,
            "timestamp": datetime.now().isoformat(),
        })

        # Keep connection alive
        while True:
            try:
                # Wait for messages from client (ping/pong or commands)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=60.0
                )

                # Handle ping
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "keepalive"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("websocket_error", error=str(e))
    finally:
        ws_manager.disconnect(websocket)


# =============================================================================
# Static Files (Vue Frontend)
# =============================================================================

# Determine frontend dist path (works in Docker and local dev)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

# Check if built frontend exists
if FRONTEND_DIST.exists():
    # Mount static assets (js, css, etc.)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    async def serve_spa():
        """Serve the Vue SPA."""
        return FileResponse(FRONTEND_DIST / "index.html")

    # Catch-all for Vue Router (SPA routing)
    @app.get("/{path:path}")
    async def serve_spa_routes(path: str):
        """Serve Vue SPA for all non-API routes."""
        # Check if it's a static file
        file_path = FRONTEND_DIST / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html for Vue Router
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    # Development mode fallback - show API info
    logger.warning("frontend_not_built", path=str(FRONTEND_DIST))

    @app.get("/")
    async def root():
        """Root endpoint with basic status page (frontend not built)."""
        status = await camera_controller.get_status()
        return {
            "application": "Nikon D500 Camera Control",
            "version": "0.1.0",
            "message": "Frontend not built. Run 'cd frontend && npm install && npm run build' or use Docker.",
            "camera": status,
            "docs": "/docs",
            "warning": "IMPORTANT: Set camera mode dial to P, A, S, or M for remote control to work!",
        }
