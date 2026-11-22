"""File-backed application configuration (no environment variables).

``AppConfig`` is persisted as JSON; ``ConfigStore`` provides atomic writes, validated
deep-merge updates, change subscriptions and restart-required reporting.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.errors import ConfigInvalid
from backend.core.security import ApiKeyStore

log = logging.getLogger(__name__)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CameraConfig(_Section):
    keepalive_enabled: bool = Field(
        default=True, description="Send periodic keepalives (D500 times out at 60 s)"
    )
    keepalive_interval_s: float = Field(
        default=30.0, ge=5.0, le=55.0, description="Keepalive interval"
    )
    connect_timeout_s: float = Field(
        default=10.0, ge=1.0, le=120.0, description="Timeout for one connect attempt"
    )
    connect_retries: int = Field(
        default=5, ge=0, le=50, description="Reconnect attempts after a lost link"
    )
    reconnect_interval_s: float = Field(
        default=2.0, ge=0.5, le=60.0, description="Delay between reconnects"
    )
    capture_timeout_s: float = Field(default=30.0, ge=0.1, le=300.0, description="Capture timeout")
    event_quiet_window_s: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="After a capture, stop draining camera events after this quiet period",
    )


class LiveViewConfig(_Section):
    target_fps: int = Field(default=8, ge=1, le=30, description="Target live view frame rate")
    frame_timeout_s: float = Field(
        default=0.5, ge=0.1, le=5.0, description="Max wait for one frame"
    )
    quality: Literal["small", "medium", "large"] = Field(
        default="medium", description="Frame size preset"
    )
    jpeg_quality: int = Field(
        default=75, ge=10, le=100, description="Re-encode quality for streamed frames"
    )
    max_width: int | None = Field(
        default=None,
        ge=64,
        le=8192,
        description="Downscale frames wider than this (px); None = off",
    )


class TimelapseConfig(_Section):
    min_interval_s: float = Field(
        default=1.0, ge=0.1, le=3600.0, description="Minimum frame interval"
    )
    max_duration_s: int = Field(
        default=86400, ge=60, le=30 * 86400, description="Maximum session length"
    )
    failure_budget: int = Field(
        default=5, ge=1, le=100, description="Consecutive failed frames before abort"
    )


class VideoConfig(_Section):
    ffmpeg_path: str | None = Field(
        default=None, description="Path to the ffmpeg binary; None = autodetect"
    )
    codec: Literal["libx264", "libx265", "libvpx-vp9"] = Field(
        default="libx264", description="ffmpeg codec"
    )
    crf: int = Field(default=23, ge=0, le=51, description="Constant rate factor (lower is better)")
    preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = Field(default="medium", description="ffmpeg preset")
    fps: int = Field(default=24, ge=1, le=120, description="Output frame rate")
    timeout_s: int = Field(default=3600, ge=10, le=86400, description="ffmpeg run timeout")


class MediaConfig(_Section):
    thumbnail_size: int = Field(
        default=200, ge=32, le=1024, description="Thumbnail longest edge (px)"
    )
    download_concurrency: int = Field(
        default=2, ge=1, le=8, description="Parallel camera downloads"
    )


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Fields whose change only takes effect after an app restart (top-level or "section.field").
    RESTART_REQUIRED_FIELDS: ClassVar[frozenset[str]] = frozenset({"cors_origins"})

    camera: CameraConfig = Field(default_factory=CameraConfig)
    liveview: LiveViewConfig = Field(default_factory=LiveViewConfig)
    timelapse: TimelapseConfig = Field(default_factory=TimelapseConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    cors_origins: list[str] = Field(
        default_factory=list, description="Allowed CORS origins; empty = same-origin only"
    )
    demo_camera: bool = Field(default=False, description="Use the simulated camera")
    api_key_hash: str | None = Field(default=None, description="sha256 of the API key; None = open")

    def public_dump(self) -> dict[str, Any]:
        """JSON-safe dump for API output: the hash is replaced by ``api_key_set``."""
        out = self.model_dump(mode="json", exclude={"api_key_hash"})
        out["api_key_set"] = self.api_key_hash is not None
        return out

    @classmethod
    def public_schema(cls) -> dict[str, Any]:
        """JSON schema of the public config (titles, descriptions, constraints)."""
        schema = cls.model_json_schema()
        schema.get("properties", {}).pop("api_key_hash", None)
        schema.setdefault("properties", {})["api_key_set"] = {
            "type": "boolean",
            "title": "Api Key Set",
            "description": "Whether an API key is configured (read-only)",
            "readOnly": True,
        }
        return schema


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _changed_paths(old: Any, new: Any, prefix: str = "") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        res: list[str] = []
        for k in new:
            res += _changed_paths(old.get(k), new[k], f"{prefix}{k}.")
        return res
    return [] if old == new else [prefix.rstrip(".")]


def _drop_invalid(data: dict[str, Any], exc: ValidationError) -> bool:
    """Remove every field ``exc`` complains about (unknown or invalid); True if any removed."""
    removed = False
    for err in exc.errors():
        node: Any = data
        loc = err["loc"]
        for i, part in enumerate(loc):
            last = i == len(loc) - 1
            if isinstance(node, dict) and part in node:
                if last or not isinstance(node[part], dict):
                    path = ".".join(map(str, loc[: i + 1]))
                    log.warning("config: dropping %s (%s)", path, err["msg"])
                    del node[part]
                    removed = True
                    break
                node = node[part]
            else:
                break
    return removed


def _restart_fields(changed: list[str]) -> list[str]:
    return [
        c
        for c in changed
        if c in AppConfig.RESTART_REQUIRED_FIELDS
        or c.split(".")[0] in AppConfig.RESTART_REQUIRED_FIELDS
    ]


Subscriber = Callable[[AppConfig, AppConfig], None]


class ConfigStore:
    """Thread-safe store.

    - ``config`` is an immutable snapshot (AppConfig is frozen).
    - ``update`` deep-merges ``patch`` into the current config, validates, persists
      atomically, notifies subscribers ``callback(new, old)`` (only if something changed;
      exceptions in callbacks are logged), and returns ``(new_config, restart_fields)``
      where restart_fields lists changed dotted paths in ``RESTART_REQUIRED_FIELDS``.
      Invalid patches raise ``ConfigInvalid`` (details["errors"]) and change nothing.
    - A missing file yields defaults (``initial`` if given). Loading is lenient: unknown
      fields are dropped and invalid fields fall back to their defaults (each logged);
      only unparseable JSON is renamed to ``<name>.corrupt-<ts>``.
    - The API key hash lives in ``api_key.json`` next to the config (see ``ApiKeyStore``),
      never in config.json. A broken key file fails closed (auth on, all keys rejected).
    """

    def __init__(self, path: Path, initial: AppConfig | None = None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._subscribers: list[Subscriber] = []
        self._keys = ApiKeyStore(self._path.with_name("api_key.json"))
        self._config = self._load(initial)

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def path(self) -> Path:
        return self._path

    def _load(self, initial: AppConfig | None) -> AppConfig:
        default = initial if initial is not None else AppConfig()
        legacy_hash: str | None = None
        cfg = default
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raw = None
        except OSError:
            log.warning("config unreadable: %s", self._path)
            raw = None
        if raw is not None:
            data: Any = None
            try:
                data = json.loads(raw)
            except ValueError:
                pass
            if isinstance(data, dict):
                legacy = data.pop("api_key_hash", None)
                legacy_hash = legacy if isinstance(legacy, str) and legacy else None
                cfg = self._lenient(data, default)
            else:
                aside = self._path.with_name(f"{self._path.name}.corrupt-{int(time.time())}")
                log.error("config is not valid JSON; moving aside to %s", aside)
                try:
                    os.replace(self._path, aside)
                except OSError:
                    log.warning("could not move corrupt config aside: %s", self._path)
        if self._keys.path.exists():
            key_hash = self._keys.load()
        elif legacy_hash is not None:  # migrate the hash out of config.json
            self._keys.save(legacy_hash)
            key_hash = legacy_hash
            log.info("migrated API key hash from config.json to %s", self._keys.path)
            with contextlib.suppress(OSError):
                self._write(cfg)
        else:
            key_hash = cfg.api_key_hash
        return cfg.model_copy(update={"api_key_hash": key_hash})

    @staticmethod
    def _lenient(data: dict[str, Any], default: AppConfig) -> AppConfig:
        for _ in range(50):
            try:
                return AppConfig.model_validate(data)
            except ValidationError as exc:
                if not _drop_invalid(data, exc):
                    break
        log.error("config could not be repaired; using defaults")
        return default

    def _write(self, cfg: AppConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg.model_dump(mode="json", exclude={"api_key_hash"}), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def update(self, patch: dict[str, Any]) -> tuple[AppConfig, list[str]]:
        if "api_key_hash" in patch:
            raise ConfigInvalid(
                "api_key_hash cannot be set through update", details={"fields": ["api_key_hash"]}
            )
        with self._lock:
            old = self._config
            merged = _deep_merge(old.model_dump(mode="json"), patch)
            try:
                new = AppConfig.model_validate(merged)
            except ValidationError as exc:
                raise ConfigInvalid(
                    "Invalid configuration",
                    details={
                        "errors": json.loads(exc.json(include_url=False, include_input=False))
                    },
                ) from exc
            changed = _changed_paths(old.model_dump(mode="json"), new.model_dump(mode="json"))
            if changed:
                self._write(new)
                self._config = new
            subs = list(self._subscribers)
        if changed:
            self._notify(subs, new, old)
        return new, _restart_fields(changed)

    def reset(self) -> tuple[AppConfig, list[str]]:
        """Restore defaults and persist; the API key hash is preserved.

        Returns ``(new_config, restart_fields)`` like ``update``.
        """
        with self._lock:
            old = self._config
            new = AppConfig(api_key_hash=old.api_key_hash)
            changed = _changed_paths(old.model_dump(mode="json"), new.model_dump(mode="json"))
            self._write(new)
            self._config = new
            subs = list(self._subscribers)
        if new != old:
            self._notify(subs, new, old)
        return new, _restart_fields(changed)

    def set_api_key_hash(self, key_hash: str | None) -> AppConfig:
        """Set or clear the API key hash (``api_key.json``; notifies subscribers)."""
        with self._lock:
            old = self._config
            new = old.model_copy(update={"api_key_hash": key_hash})
            if new != old:
                if key_hash is None:
                    self._keys.clear()
                else:
                    self._keys.save(key_hash)
                self._config = new
            subs = list(self._subscribers)
        if new != old:
            self._notify(subs, new, old)
        return new

    def public_schema(self) -> dict[str, Any]:
        return AppConfig.public_schema()

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register ``callback(new, old)``; returns an unsubscribe function."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock, contextlib.suppress(ValueError):
                self._subscribers.remove(callback)

        return unsubscribe

    @staticmethod
    def _notify(subs: list[Subscriber], new: AppConfig, old: AppConfig) -> None:
        for cb in subs:
            try:
                cb(new, old)
            except Exception:
                log.exception("config subscriber failed")
