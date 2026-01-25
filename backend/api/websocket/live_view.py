"""
Live View WebSocket Handler

Provides real-time camera preview via binary WebSocket frames.
"""

import asyncio
from datetime import datetime
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from backend.camera.live_view import LiveViewHandler
from backend.camera.exceptions import LiveViewError

logger = structlog.get_logger(__name__)


class LiveViewWebSocketHandler:
    """
    Manages WebSocket connections for live view streaming.

    Supports multiple concurrent viewers with a single camera stream.
    """

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.live_view_handler: Optional[LiveViewHandler] = None
        self._streaming_task: Optional[asyncio.Task] = None

    def set_handler(self, handler: LiveViewHandler) -> None:
        """Set the live view handler."""
        self.live_view_handler = handler

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

        logger.info(
            "liveview_client_connected",
            total_clients=len(self.active_connections)
        )

        # Send initial status
        if self.live_view_handler:
            status = await self.live_view_handler.get_status()
            await websocket.send_json({
                "type": "status",
                "data": status,
                "timestamp": datetime.now().isoformat()
            })

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        logger.info(
            "liveview_client_disconnected",
            remaining_clients=len(self.active_connections)
        )

    async def broadcast_frame(self, frame: bytes) -> None:
        """
        Send a frame to all connected clients.

        Uses binary WebSocket frames for efficiency.
        """
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_bytes(frame)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_status(self, status: dict) -> None:
        """Send status update to all connected clients."""
        message = {
            "type": "status",
            "data": status,
            "timestamp": datetime.now().isoformat()
        }

        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    async def handle_connection(self, websocket: WebSocket) -> None:
        """
        Handle a single WebSocket connection for live view.

        This method:
        1. Accepts the connection
        2. Starts live view if not already active
        3. Streams frames to the client
        4. Stops live view when last client disconnects
        """
        await self.connect(websocket)

        try:
            if not self.live_view_handler:
                await websocket.send_json({
                    "type": "error",
                    "message": "Live view handler not initialized",
                    "timestamp": datetime.now().isoformat()
                })
                return

            # Start live view if this is the first client
            if len(self.active_connections) == 1:
                try:
                    await self.live_view_handler.start()
                except LiveViewError as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now().isoformat()
                    })
                    return

            # Stream frames
            try:
                async for frame in self.live_view_handler.stream_frames():
                    # Check if this client is still connected
                    if websocket not in self.active_connections:
                        break

                    # Send frame to this client only
                    # (each client runs its own handler)
                    try:
                        await websocket.send_bytes(frame)
                    except Exception:
                        break

                    # Handle any incoming messages (ping, commands)
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_json(),
                            timeout=0.001  # Non-blocking check
                        )
                        await self._handle_client_message(websocket, data)
                    except asyncio.TimeoutError:
                        pass  # No message, continue streaming
                    except Exception:
                        pass

            except LiveViewError as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                })

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("liveview_websocket_error", error=str(e))
        finally:
            self.disconnect(websocket)

            # Stop live view if this was the last client
            if len(self.active_connections) == 0 and self.live_view_handler:
                await self.live_view_handler.stop()

    async def _handle_client_message(self, websocket: WebSocket, data: dict) -> None:
        """Handle messages from the client."""
        message_type = data.get("type")

        if message_type == "ping":
            await websocket.send_json({"type": "pong"})

        elif message_type == "get_status":
            if self.live_view_handler:
                status = await self.live_view_handler.get_status()
                await websocket.send_json({
                    "type": "status",
                    "data": status,
                    "timestamp": datetime.now().isoformat()
                })

        elif message_type == "stop":
            # Client requested to stop their stream
            self.disconnect(websocket)


# Global instance
liveview_ws_handler = LiveViewWebSocketHandler()
