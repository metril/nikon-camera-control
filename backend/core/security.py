"""Optional API-key authentication. Only a sha256 hash of the key is ever stored."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, Request, WebSocket
from fastapi.security import APIKeyHeader

from backend.core.errors import Unauthorized

log = logging.getLogger(__name__)

# Stored in place of the key hash when api_key.json exists but is unusable: never equals a
# sha256 hex digest, so every key is rejected (fail closed).
LOCKED_HASH = "!locked"

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


class ApiKeyStore:
    """The API key hash, kept in its own file (``{"sha256", "created"}``), written atomically.

    Missing file = no key (open mode). Present but unreadable/invalid = FAIL CLOSED
    (``load`` returns ``LOCKED_HASH``). Recovery from lockout: delete the file on the host.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            return self._locked(f"unreadable: {exc}")
        try:
            data = json.loads(raw)
            digest = data["sha256"]
            if not (isinstance(digest, str) and len(digest) == 64):
                raise ValueError("sha256 must be a 64-character hex string")
            int(digest, 16)
        except (ValueError, KeyError, TypeError) as exc:
            return self._locked(f"invalid: {exc!r}")
        return digest

    def _locked(self, why: str) -> str:
        log.error(
            "API key file %s is %s. Authentication stays ENABLED and every key is rejected. "
            "Delete this file on the host to remove the key and re-open the app.",
            self._path,
            why,
        )
        return LOCKED_HASH

    def save(self, key_hash: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".api_key-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"sha256": key_hash, "created": datetime.now(UTC).isoformat()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


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
    """Authorize a WebSocket; call before accepting.

    The key is taken only from the ``apikey.<key>`` subprotocol (never the URL, which
    would leak it into access logs). Returns True if allowed (always in open mode); the
    caller then accepts, echoing ``ws_subprotocol``. On failure it accepts and closes
    with 4401 (closing before accept would surface as HTTP 403) and returns False; the
    caller must then return.
    """
    key_hash = _current_hash(websocket.app.state)
    if not key_hash:
        return True
    proto = ws_subprotocol(websocket)
    key = proto.removeprefix("apikey.") if proto else None
    if verify_api_key(key, key_hash):
        return True
    await websocket.accept(subprotocol=proto)
    await websocket.close(code=4401, reason="Missing or invalid API key")
    return False


def ws_subprotocol(websocket: WebSocket) -> str | None:
    """The ``apikey.<key>`` subprotocol offered by the client, if any (echo it on accept)."""
    for proto in websocket.scope.get("subprotocols", []):
        if proto.startswith("apikey."):
            return str(proto)
    return None
