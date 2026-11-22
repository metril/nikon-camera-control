"""Cross-origin guard (CSRF / cross-site WebSocket hijacking protection).

Browsers send "simple" cross-origin POSTs without a CORS preflight and never apply CORS to
WebSocket handshakes, so in open mode (no API key) any web page could drive the camera.
Rule: for unsafe HTTP methods (POST, PUT, PATCH, DELETE) and WebSocket handshakes, an
``Origin`` header, when present, must be same-origin (host and port equal to the request's
``Host``, scheme ignored) or listed in ``config.cors_origins`` (read live). Otherwise HTTP
gets 403 ``FORBIDDEN_ORIGIN`` and the WebSocket is closed with 4403 before it is accepted.
Requests without ``Origin`` (curl, scripts) and safe methods are not affected.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.api.errors import _envelope
from backend.core.config_store import ConfigStore
from backend.core.errors import ErrorCode, ForbiddenOrigin

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
WS_CLOSE_FORBIDDEN_ORIGIN = 4403


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return str(v.decode("latin-1"))
    return None


def origin_allowed(origin: str, host: str | None, allowed: list[str]) -> bool:
    """Same host:port as ``host`` (scheme-insensitive) or listed in ``allowed``."""
    norm = origin.strip().rstrip("/").lower()
    if norm in {a.strip().rstrip("/").lower() for a in allowed}:
        return True
    if not host:
        return False
    try:
        netloc = urlsplit(norm).netloc
    except ValueError:
        return False
    return bool(netloc) and netloc == host.strip().lower()


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp, config_store: ConfigStore) -> None:
        self.app = app
        self._store = config_store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        guarded = kind == "websocket" or (kind == "http" and scope["method"] in UNSAFE_METHODS)
        if guarded:
            origin = _header(scope, b"origin")
            if origin is not None and not origin_allowed(
                origin, _header(scope, b"host"), self._store.config.cors_origins
            ):
                if kind == "websocket":
                    await receive()  # websocket.connect
                    await send(
                        {
                            "type": "websocket.close",
                            "code": WS_CLOSE_FORBIDDEN_ORIGIN,
                            "reason": "Cross-origin WebSocket not allowed",
                        }
                    )
                    return
                exc = ForbiddenOrigin(details={"origin": origin})
                resp = _envelope(
                    Request(scope),
                    exc.http_status,
                    ErrorCode.FORBIDDEN_ORIGIN,
                    exc.message,
                    exc.details,
                )
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)
