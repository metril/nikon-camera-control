"""Persistent presets (``<data_dir>/presets.json``): camera-setting sets and bracket sets.

Writes are atomic (tmp + ``os.replace``) under one lock. A corrupt or too-new file is moved
aside and reported through ``warning``; it never crashes the app. Built-in bracket presets from
the time-lapse module are listed read-only with stable ids ``builtin-<name>``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from backend.api.schemas.common import EventType
from backend.api.schemas.presets import (
    SCHEMA_VERSION,
    AppliedSetting,
    ApplyResult,
    BracketPreset,
    BracketPresetIn,
    FromCameraIn,
    ImportItemResult,
    Preset,
    PresetCollection,
    PresetExport,
    PresetImportIn,
    PresetImportResult,
    PresetIn,
    SettingsPreset,
    SettingsPresetIn,
    SkippedSetting,
)
from backend.api.schemas.timelapse import (
    BracketStep,
    PresetBracketing,
    QuickBracketing,
    ResolvedStep,
    StepsBracketing,
)
from backend.core.errors import (
    AppError,
    ConfigInvalid,
    Forbidden,
    InvalidState,
    PresetNotFound,
    SettingNotAllowed,
    SettingNotFound,
)
from backend.core.events import EventBus
from backend.services.settings import COMMON, WRITABLE, SettingsService, resolve_name
from backend.services.timelapse.brackets import (
    PRESETS,
    generate_quick,
    normalise_steps,
    preset_steps,
)
from backend.services.timelapse.config import validate_steps

log = logging.getLogger(__name__)

FILE_NAME = "presets.json"
BUILTIN_PREFIX = "builtin-"
_PRESET = TypeAdapter(Preset)
_PRESET_IN = TypeAdapter(PresetIn)
_WRITABLE = frozenset(WRITABLE)
DEFAULT_FROM_CAMERA: tuple[str, ...] = tuple(n for n in COMMON if n in _WRITABLE)


def _builtins() -> list[BracketPreset]:
    return [
        BracketPreset(
            id=f"{BUILTIN_PREFIX}{name}",
            builtin=True,
            name=name,
            description=p.description,
            bracketing=PresetBracketing(preset=name),
        )
        for name, p in PRESETS.items()
    ]


def bracket_steps(b: StepsBracketing | QuickBracketing | PresetBracketing) -> list[BracketStep]:
    """Normalised steps of a bracketing (offline; raises ConfigInvalid)."""
    if isinstance(b, StepsBracketing):
        return normalise_steps(list(b.steps))
    if isinstance(b, PresetBracketing):
        return normalise_steps(preset_steps(b.preset))
    steps = generate_quick(b)
    if not steps:
        raise ConfigInvalid("Quick bracketing needs at least one type with values")
    return normalise_steps(steps)


def _check_settings_names(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in values.items():
        w = resolve_name(k)
        if w not in _WRITABLE:
            raise SettingNotAllowed(
                f"Setting {k!r} cannot be stored in a preset", details={"name": k}
            )
        if w in out:
            raise ConfigInvalid(f"Setting {w!r} given more than once", details={"name": w})
        out[w] = v
    return out


class PresetService:
    def __init__(
        self,
        data_dir: Path,
        settings: SettingsService,
        *,
        clock: Callable[[], datetime] | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._path = data_dir / FILE_NAME
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._items: dict[str, Preset] | None = None
        self._warning: str | None = None
        self._bus = bus
        self._unreadable = False  # file exists but could not be read: never overwrite it
        self._backup_pending = False  # entries were skipped on load: keep the original aside

    # persistence ------------------------------------------------------------------------
    def _read(self) -> tuple[dict[str, Preset], str | None]:
        """Sets ``_unreadable`` / ``_backup_pending`` (called under the lock)."""
        self._unreadable = self._backup_pending = False
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}, None
        except OSError as e:
            self._unreadable = True
            return {}, f"presets file unreadable ({e}); changes are refused until it is readable"
        try:
            doc = json.loads(raw)
            if not isinstance(doc, dict) or not isinstance(doc.get("presets"), list):
                raise ValueError("not a presets document")
            if int(doc.get("schema_version", 0)) > SCHEMA_VERSION:
                raise ValueError(f"schema_version {doc.get('schema_version')} is too new")
        except (ValueError, TypeError) as e:
            aside = self._path.with_name(f"{FILE_NAME}.corrupt-{int(time.time() * 1000)}")
            with contextlib.suppress(OSError):
                os.replace(self._path, aside)
            log.warning("presets file invalid (%s); moved to %s", e, aside)
            return {}, f"presets file was invalid ({e}); moved to {aside.name}"
        items: dict[str, Preset] = {}
        skipped = 0
        for entry in doc["presets"]:
            try:
                p = _PRESET.validate_python(entry)
                if p.id.startswith(BUILTIN_PREFIX) or p.id in items:
                    raise ValueError("bad id")
                p.builtin = False
                items[p.id] = p
            except (ValidationError, ValueError):
                skipped += 1
        self._backup_pending = skipped > 0
        return items, (f"{skipped} invalid preset(s) skipped" if skipped else None)

    def _write(self, items: dict[str, Preset]) -> str | None:
        """Atomic write; returns the backup file name if the original was copied aside."""
        bak: str | None = None
        if self._backup_pending:
            dest = self._path.with_name(f"{FILE_NAME}.bak-{int(time.time() * 1000)}")
            shutil.copy2(self._path, dest)  # raises (nothing lost) if the copy fails
            bak = dest.name
            self._backup_pending = False
        doc = {
            "schema_version": SCHEMA_VERSION,
            "presets": [p.model_dump(mode="json") for p in items.values()],
        }
        tmp = self._path.with_name(f"{FILE_NAME}.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return bak

    async def _load(self) -> dict[str, Preset]:
        """Call with the lock held. An unreadable file is re-read on every call."""
        if self._items is None or self._unreadable:
            items, self._warning = await asyncio.to_thread(self._read)
            self._items = items
            return items
        return self._items

    async def _commit(self, items: dict[str, Preset]) -> None:
        if self._unreadable:
            raise InvalidState(
                "The presets file exists but cannot be read; changes are refused so that "
                "nothing is overwritten. Fix the file or its permissions and retry.",
                details={"file": FILE_NAME},
            )
        bak = await asyncio.to_thread(self._write, items)
        self._items = items
        if bak:
            self._warning = f"{self._warning or 'invalid presets skipped'}; original kept as {bak}"

    def _changed(self, action: str, preset: Preset | None = None) -> None:
        if self._bus is not None:
            self._bus.publish(
                EventType.PRESETS_CHANGED,
                {
                    "action": action,
                    "id": preset.id if preset else None,
                    "kind": preset.kind if preset else None,
                },
            )

    # helpers ----------------------------------------------------------------------------
    @staticmethod
    def _new_id(taken: dict[str, Preset]) -> str:
        while True:
            i = secrets.token_hex(5)
            if i not in taken:
                return i

    @staticmethod
    def _check_name_free(
        items: dict[str, Preset], kind: str, name: str, *, ignore: str | None = None
    ) -> None:
        low = name.lower()
        pool: list[Preset] = list(items.values())
        if kind == "bracket":
            pool += _builtins()
        for p in pool:
            if p.kind == kind and p.id != ignore and p.name.lower() == low:
                raise InvalidState(
                    f"A {kind} preset named {name!r} already exists", details={"name": name}
                )

    @staticmethod
    def _validate(body: SettingsPresetIn | BracketPresetIn) -> SettingsPresetIn | BracketPresetIn:
        if isinstance(body, SettingsPresetIn):
            return body.model_copy(update={"values": _check_settings_names(body.values)})
        bracket_steps(body.bracketing)
        return body

    def _find(self, items: dict[str, Preset], preset_id: str) -> Preset:
        if preset_id.startswith(BUILTIN_PREFIX):
            for b in _builtins():
                if b.id == preset_id:
                    return b
        p = items.get(preset_id)
        if p is None:
            raise PresetNotFound(f"Preset {preset_id!r} not found", details={"id": preset_id})
        return p

    # CRUD -------------------------------------------------------------------------------
    async def list(self, kind: Literal["settings", "bracket"] | None = None) -> PresetCollection:
        async with self._lock:
            items = await self._load()
            allp: list[Preset] = [*_builtins(), *items.values()]
            return PresetCollection(
                items=[p for p in allp if kind is None or p.kind == kind], warning=self._warning
            )

    async def get(self, preset_id: str) -> Preset:
        async with self._lock:
            return self._find(await self._load(), preset_id)

    async def create(self, body: SettingsPresetIn | BracketPresetIn) -> Preset:
        body = self._validate(body)
        async with self._lock:
            items = await self._load()
            self._check_name_free(items, body.kind, body.name)
            return await self._add(items, body)

    async def _add(
        self,
        items: dict[str, Preset],
        body: SettingsPresetIn | BracketPresetIn,
        preset_id: str | None = None,
    ) -> Preset:
        now = self._clock()
        data = {
            **body.model_dump(),
            "id": preset_id or self._new_id(items),
            "created": now,
            "updated": now,
        }
        p = _PRESET.validate_python(data)
        await self._commit({**items, p.id: p})
        self._changed("created", p)
        return p

    async def update(self, preset_id: str, body: SettingsPresetIn | BracketPresetIn) -> Preset:
        body = self._validate(body)
        async with self._lock:
            items = await self._load()
            cur = self._find(items, preset_id)
            if cur.builtin:
                raise Forbidden("Built-in presets are read-only", details={"id": preset_id})
            if cur.kind != body.kind:
                raise ConfigInvalid("A preset's kind cannot change", details={"id": preset_id})
            self._check_name_free(items, body.kind, body.name, ignore=preset_id)
            data = {**body.model_dump(), "id": cur.id, "created": cur.created}
            p = _PRESET.validate_python({**data, "updated": self._clock()})
            await self._commit({**items, p.id: p})
            self._changed("updated", p)
            return p

    async def delete(self, preset_id: str) -> None:
        async with self._lock:
            items = await self._load()
            cur = self._find(items, preset_id)
            if cur.builtin:
                raise Forbidden("Built-in presets are read-only", details={"id": preset_id})
            await self._commit({k: v for k, v in items.items() if k != preset_id})
            self._changed("deleted", cur)

    # apply ------------------------------------------------------------------------------
    async def apply(self, preset_id: str) -> ApplyResult:
        p = await self.get(preset_id)
        if isinstance(p, SettingsPreset):
            res = await self._settings.set_many(dict(p.values), skip_unusable=True)
            return ApplyResult(
                kind="settings",
                preset_id=p.id,
                applied=[AppliedSetting(name=v.name, value=v.value) for v in res.applied],
                skipped=[SkippedSetting(name=x.name, reason=x.reason) for x in res.skipped],
            )
        steps = await validate_steps(bracket_steps(p.bracketing), self._settings)
        return ApplyResult(
            kind="bracket",
            preset_id=p.id,
            steps=[
                ResolvedStep(index=i, label=s.label, settings=s.settings, delay_ms=s.delay_ms)
                for i, s in enumerate(steps)
            ],
        )

    async def from_camera(self, body: FromCameraIn) -> Preset:
        values: dict[str, Any] = {}
        if body.names is None:
            for n in DEFAULT_FROM_CAMERA:
                try:
                    values.update(await self._settings.snapshot([n], skip_readonly=True))
                except SettingNotFound:
                    continue  # this body does not have the widget
        else:
            names = list(_check_settings_names(dict.fromkeys(body.names)))
            values = await self._settings.snapshot(names)
        if not values:
            raise ConfigInvalid("The camera reported none of the requested settings")
        return await self.create(
            SettingsPresetIn(name=body.name, description=body.description, values=values)
        )

    # export / import --------------------------------------------------------------------
    async def export(self) -> PresetExport:
        async with self._lock:
            items = await self._load()
            return PresetExport(exported=self._clock(), presets=list(items.values()))

    async def import_(self, doc: PresetImportIn) -> PresetImportResult:
        async with self._lock:
            items = await self._load()
            base: dict[str, Preset] = {} if doc.replace else dict(items)
            results: list[ImportItemResult] = []
            for i, raw in enumerate(doc.presets):
                name = raw.get("name") if isinstance(raw.get("name"), str) else None
                try:
                    body = self._validate(_PRESET_IN.validate_python(raw))
                    self._check_name_free(base, body.kind, body.name)
                except ValidationError as e:
                    first = e.errors()[0]
                    where = ".".join(str(x) for x in first["loc"])
                    results.append(
                        ImportItemResult(
                            index=i, name=name, status="error", error=f"{where}: {first['msg']}"
                        )
                    )
                    continue
                except InvalidState as e:
                    results.append(
                        ImportItemResult(index=i, name=name, status="skipped", error=e.message)
                    )
                    continue
                except AppError as e:
                    results.append(
                        ImportItemResult(index=i, name=name, status="error", error=e.message)
                    )
                    continue
                want = raw.get("id")
                pid = (
                    want
                    if isinstance(want, str)
                    and want not in base
                    and not want.startswith(BUILTIN_PREFIX)
                    and _valid_id(want)
                    else self._new_id(base)
                )
                now = self._clock()
                p = _PRESET.validate_python(
                    {**body.model_dump(), "id": pid, "created": now, "updated": now}
                )
                base[p.id] = p
                results.append(ImportItemResult(index=i, name=p.name, id=p.id, status="created"))
            if any(r.status == "created" for r in results) or (doc.replace and items):
                await self._commit(base)
                self._changed("imported")
            return PresetImportResult(
                created=sum(r.status == "created" for r in results),
                skipped=sum(r.status == "skipped" for r in results),
                failed=sum(r.status == "error" for r in results),
                items=results,
            )


def _valid_id(s: str) -> bool:
    return re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", s) is not None
