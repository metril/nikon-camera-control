"""Optional API-key authentication. Only a sha256 hash of the key is ever stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, Request, WebSocket
from fastapi.security import APIKeyHeader

from backend.core.errors import Unauthorized

# Registers the header as an OpenAPI security scheme; enforcement is in require_api_key.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    """Hex sha256 of the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str | None, key_hash: str | None) -> bool:
    """True if no hash is configured (open mode) or sha256(key) matches via compare_digest."""
    if not key_hash:
        return True
    if not key:
        return False
    return hmac.compare_digest(hash_api_key(key), key_hash)


def generate_api_key() -> str:
    """New random URL-safe key (shown to the user once)."""
    return secrets.token_urlsafe(32)


def _current_hash(state: object) -> str | None:
    store = getattr(state, "config_store", None)
    return store.config.api_key_hash if store is not None else None


async def require_api_key(request: Request, _scheme: str | None = Depends(api_key_header)) -> None:
    """FastAPI dependency for REST routes.

    Reads the current hash from ``request.app.state.config_store.config.api_key_hash``
    on every call (so rotation applies live) and the ``X-API-Key`` header.
    Raises ``Unauthorized`` (401) on mismatch. No-op when no hash is configured.
    Health, docs and the SPA do not use this dependency.
    """
    key = _scheme
    if not verify_api_key(key, _current_hash(request.app.state)):
        raise Unauthorized()


async def ws_authorize(websocket: WebSocket) -> bool:
    """Authorize a WebSocket before accept().

    Accepts key via subprotocol ``apikey.<key>`` (preferred; caller must echo the
    chosen subprotocol on accept) or ``?api_key=`` query fallback. Returns True if
    allowed (always True in open mode). On failure it closes with code 4401 and
    returns False; the caller must then return without accepting.
    """
    key_hash = _current_hash(websocket.app.state)
    if not key_hash:
        return True
    key: str | None = websocket.query_params.get("api_key")
    proto = ws_subprotocol(websocket)
    if proto:
        key = proto.removeprefix("apikey.")
    if verify_api_key(key, key_hash):
        return True
    await websocket.close(code=4401)
    return False


def ws_subprotocol(websocket: WebSocket) -> str | None:
    """The ``apikey.<key>`` subprotocol offered by the client, if any (echo it on accept)."""
    for proto in websocket.scope.get("subprotocols", []):
        if proto.startswith("apikey."):
            return str(proto)
    return None
