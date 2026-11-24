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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.core.clock import validate_zone
from backend.core.errors import ConfigInvalid
from backend.core.security import ApiKeyStore

log = logging.getLogger(__name__)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CameraConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Camera")

    keepalive_enabled: bool = Field(
        default=True,
        title="Keep the connection alive",
        description="Send a keepalive now and then. The D500 drops the USB link after 60 s idle.",
    )
    keepalive_interval_s: float = Field(
        default=30.0,
        ge=5.0,
        le=55.0,
        title="Keepalive interval",
        description="How often to send a keepalive. Keep it below 60 s.",
    )
    connect_timeout_s: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        title="Connect timeout",
        description="How long to wait for the camera before giving up.",
    )
    connect_retries: int = Field(
        default=5,
        ge=0,
        le=50,
        title="Reconnect attempts",
        description="How many times to try again after the link is lost.",
    )
    reconnect_interval_s: float = Field(
        default=2.0,
        ge=0.5,
        le=60.0,
        title="Reconnect delay",
        description="Wait this long between reconnect attempts.",
    )
    capture_timeout_s: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        title="Capture timeout",
        description="How long to wait for a photo to arrive before reporting a failure.",
    )
    event_quiet_window_s: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        title="Event quiet period",
        description="After a capture, stop listening for camera events once none arrive "
        "for this long.",
    )
    keep_card_copy: bool = Field(
        default=True,
        title="Keep a copy on the camera card",
        description="Turn off to delete the card copy once the download is verified. "
        "Only applies when the camera saves to the memory card.",
    )
    download_photos: bool = Field(
        default=True,
        title="Download photos",
        description="Turn off to only fire the shutter. Photos stay on the camera's card and "
        "Shoot is ready for the next shot sooner.",
    )
    filename_prefix: str | None = Field(
        default=None,
        max_length=40,
        title="File name prefix",
        description="Added to the start of every downloaded photo's name. Up to 40 characters; "
        "spaces and symbols become dashes.",
    )
    focus_step_small: int = Field(
        default=150,
        ge=1,
        le=32767,
        title="Small focus step",
        description="Motor steps per click; lenses differ, a full sweep on a typical zoom is "
        "~6000-8000 steps.",
    )
    focus_step_large: int = Field(
        default=1000,
        ge=1,
        le=32767,
        title="Large focus step",
        description="Motor steps per click; lenses differ, a full sweep on a typical zoom is "
        "~6000-8000 steps.",
    )

    @model_validator(mode="after")
    def _focus_steps(self) -> CameraConfig:
        if self.focus_step_small > self.focus_step_large:
            raise ValueError("focus_step_small must not be larger than focus_step_large")
        return self


class LiveViewConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Live view")

    target_fps: int = Field(
        default=8,
        ge=1,
        le=30,
        title="Target frame rate",
        description="Higher is smoother but uses more USB bandwidth. 5-15 fps is typical.",
    )
    quality: Literal["small", "medium", "large"] = Field(
        default="medium", title="Frame size", description="Size of the frames the camera sends."
    )
    jpeg_quality: int = Field(
        default=75,
        ge=10,
        le=100,
        title="JPEG quality",
        description="Quality used when re-encoding streamed frames.",
    )
    max_width: int | None = Field(
        default=None,
        ge=64,
        le=8192,
        title="Maximum width",
        description="Shrink frames wider than this, in pixels. Leave empty to turn off.",
    )


class TimelapseConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Time-lapse")

    min_interval_s: float = Field(
        default=1.0,
        ge=0.1,
        le=3600.0,
        title="Shortest interval",
        description="The shortest time allowed between frames.",
    )
    max_duration_s: int = Field(
        default=86400,
        ge=60,
        le=30 * 86400,
        title="Longest session",
        description="A time-lapse stops after this long.",
    )
    failure_budget: int = Field(
        default=5,
        ge=1,
        le=100,
        title="Failed frames before stopping",
        description="Stop the time-lapse after this many failed frames in a row.",
    )


class VideoConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Video")

    ffmpeg_path: str | None = Field(
        default=None,
        title="ffmpeg path",
        description="Path to the ffmpeg program. Leave empty to detect it automatically.",
    )
    codec: Literal["libx264", "libx265", "libvpx-vp9"] = Field(
        default="libx264", title="Codec", description="Video codec used by ffmpeg."
    )
    crf: int = Field(
        default=23,
        ge=0,
        le=51,
        title="CRF",
        description="Constant rate factor. Lower means better quality and larger files.",
    )
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
    ] = Field(
        default="medium",
        title="Encoder preset",
        description="Slower presets make smaller files.",
    )
    fps: int = Field(
        default=24, ge=1, le=120, title="Frame rate", description="Frame rate of the video."
    )
    timeout_s: int = Field(
        default=3600,
        ge=10,
        le=86400,
        title="Encode timeout",
        description="Stop an ffmpeg run that takes longer than this.",
    )


class MediaConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Media")

    thumbnail_size: int = Field(
        default=200,
        ge=32,
        le=1024,
        title="Thumbnail size",
        description="Length of the longest thumbnail edge, in pixels.",
    )


class StorageLocation(_Section):
    """A configured storage location. Passwords are never stored here (see SecretStore)."""

    id: str = Field(
        pattern=r"^(usb-[0-9A-Za-z-]{1,64}|smb-[a-z0-9][a-z0-9_-]{0,31})$",
        description="usb-<fs uuid> or smb-<slug>",
    )
    kind: Literal["usb", "smb"]
    name: str = Field(default="", max_length=64, description="Display name")
    uuid: str | None = Field(default=None, pattern=r"^[0-9A-Za-z-]{1,64}$")
    unc: str | None = Field(
        default=None, pattern=r"^//[A-Za-z0-9._-]+/[A-Za-z0-9._ $-]+(/[A-Za-z0-9._ $-]+)*$"
    )
    username: str | None = Field(default=None, max_length=128, pattern=r"^[^\x00-\x1f,]*$")
    domain: str | None = Field(default=None, max_length=128, pattern=r"^[^\x00-\x1f,]*$")
    auto_mount: bool = Field(default=True, description="Mount automatically when available")

    @model_validator(mode="after")
    def _kind_fields(self) -> StorageLocation:
        if self.kind == "usb" and not self.uuid:
            raise ValueError("a USB location needs a filesystem uuid")
        if self.kind == "smb" and not self.unc:
            raise ValueError("an SMB location needs a //host/share path")
        return self


class StorageConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, title="Backups")

    locations: list[StorageLocation] = Field(
        default_factory=list, title="Locations", description="Configured storage locations."
    )
    target_id: str | None = Field(
        default=None, title="Copy photos to", description="Location that receives every photo."
    )
    backup_ids: list[str] = Field(
        default_factory=list, title="Backup locations", description="Locations used for backups."
    )
    backup_interval_min: int = Field(
        default=15,
        ge=1,
        le=1440,
        title="Backup interval",
        description="How often backups run.",
    )
    deep_verify: bool = Field(
        default=False,
        title="Verify existing backup files",
        description="Check every file already on the backup against its checksum on each run.",
    )
    sidecars: bool = Field(
        default=True,
        title="Write checksum files",
        description="Save a SHA-256 checksum file next to every photo.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> StorageConfig:
        ids = [loc.id for loc in self.locations]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate location ids")
        if self.target_id is not None and self.target_id not in ids:
            raise ValueError("target_id is not a configured location")
        if any(b not in ids for b in self.backup_ids) or len(set(self.backup_ids)) != len(
            self.backup_ids
        ):
            raise ValueError("backup_ids must be unique configured locations")
        if self.target_id is not None and self.target_id in self.backup_ids:
            raise ValueError("the target cannot also be a backup")
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Fields whose change only takes effect after an app restart (top-level or "section.field").
    RESTART_REQUIRED_FIELDS: ClassVar[frozenset[str]] = frozenset({"cors_origins"})

    camera: CameraConfig = Field(default_factory=CameraConfig)
    liveview: LiveViewConfig = Field(default_factory=LiveViewConfig)
    timelapse: TimelapseConfig = Field(default_factory=TimelapseConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    cors_origins: list[str] = Field(
        default_factory=list,
        title="Allowed web origins",
        description="Other sites allowed to call the API. Leave empty to allow only this site.",
    )
    timezone: str | None = Field(
        default=None,
        title="Time zone",
        description="IANA time zone name, e.g. America/New_York. Used for photo and session "
        "names and when setting the camera clock. Empty uses the server's own zone.",
        max_length=64,
    )
    demo_camera: bool = Field(default=False, description="Use the simulated camera")
    api_key_hash: str | None = Field(default=None, description="sha256 of the API key; None = open")

    @field_validator("timezone")
    @classmethod
    def _zone_known(cls, v: str | None) -> str | None:
        return validate_zone(v) if v else None

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
            "title": "API key set",
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


def changed_fields(old: AppConfig, new: AppConfig) -> list[str]:
    """Dotted paths of the fields that differ between two configs."""
    return _changed_paths(old.model_dump(mode="json"), new.model_dump(mode="json"))


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
        """Restore defaults and persist; the API key hash and the ``storage`` section
        (locations, target, backups; their secrets stay referenced) are preserved.

        Returns ``(new_config, restart_fields)`` like ``update``.
        """
        with self._lock:
            old = self._config
            new = AppConfig(api_key_hash=old.api_key_hash, storage=old.storage)
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
