"""Optional API-key authentication. Only a sha256 hash of the key is ever stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Request, WebSocket


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


async def require_api_key(request: Request) -> None:
    """FastAPI dependency for REST routes.

    Reads the current hash from ``request.app.state.config_store.config.api_key_hash``
    on every call (so rotation applies live) and the ``X-API-Key`` header.
    Raises ``Unauthorized`` (401) on mismatch. No-op when no hash is configured.
    Health, docs and the SPA do not use this dependency.
    """
    raise NotImplementedError


async def ws_authorize(websocket: WebSocket) -> bool:
    """Authorize a WebSocket before accept().

    Accepts key via subprotocol ``apikey.<key>`` (preferred; caller must echo the
    chosen subprotocol on accept) or ``?api_key=`` query fallback. Returns True if
    allowed (always True in open mode). On failure it closes with code 4401 and
    returns False; the caller must then return without accepting.
    """
    raise NotImplementedError


def ws_subprotocol(websocket: WebSocket) -> str | None:
    """The ``apikey.<key>`` subprotocol offered by the client, if any (echo it on accept)."""
    for proto in websocket.scope.get("subprotocols", []):
        if proto.startswith("apikey."):
            return str(proto)
    return None
