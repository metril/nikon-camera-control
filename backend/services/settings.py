"""Camera settings: typed reads, validated writes, snapshot/restore.

Reads are served from ``CameraService``'s per-connection cache. Writes are validated against
the widget's type BEFORE they reach the camera and only widgets on ``WRITABLE`` may be set
generically (``set_setting`` already publishes SETTING_CHANGED; this module does not).
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from backend.api.schemas.common import EventType
from backend.camera.backend import ConfigRange, ConfigType, ConfigWidget
from backend.core.camera_service import CameraService
from backend.core.errors import AppError, SettingInvalid, SettingNotAllowed, SettingNotFound

SettingValue = str | int | float | bool

# Friendly alias -> widget name.
ALIASES: dict[str, str] = {
    "aperture": "f-number",
    "imageformat": "imagequality",
}
_ALIAS_OF: dict[str, str] = {v: k for k, v in ALIASES.items()}

# Curated "common" list (widget names, display order). Includes read-only/dedicated ones.
COMMON: tuple[str, ...] = (
    "iso",
    "f-number",
    "shutterspeed",
    "exposurecompensation",
    "autoexposuremode",
    "focusmode",
    "autofocusdrive",
    "whitebalance",
    "imagequality",
    "imagesize",
    "liveviewsize",
    "viewfinder",
    "capturetarget",
    "meteringmode",
    "batterylevel",
)

# Generic write allowlist, in the order multi-setting writes are applied (mode before
# aperture/shutter/ISO so mode switches do not clobber the values set after them).
# Excluded on purpose: capturetarget, datetime (dedicated endpoints later) and
# autofocusdrive/manualfocusdrive/bulb/movie/viewfinder (driven by dedicated features).
WRITABLE: tuple[str, ...] = (
    "autoexposuremode",
    "expprogram",
    "focusmode",
    "focusmode2",
    "liveviewaffocus",
    "focusmetermode",
    "meteringmode",
    "drivemode",
    "f-number",
    "shutterspeed",
    "shutterspeed2",
    "isoauto",
    "iso",
    "exposurecompensation",
    "exposurecompensation2",
    "whitebalance",
    "colorspace",
    "imagequality",
    "imagesize",
    "flashmode",
    "liveviewsize",
)
_ORDER: dict[str, int] = {n: i for i, n in enumerate(WRITABLE)}

# Logical setting -> the gphoto2 widget names bodies use for it, tried in order. The first one the
# connected body has wins and is remembered for the connection (CameraService.resolve_setting).
# The D500 has no ``autoexposuremode``/``meteringmode``/``drivemode``/``isoauto``; it uses
# ``expprogram``/``exposuremetermode``/``capturemode``/``autoiso``.
SETTING_NAMES: dict[str, tuple[str, ...]] = {
    "autoexposuremode": ("autoexposuremode", "expprogram"),
    "meteringmode": ("meteringmode", "exposuremetermode"),
    "drivemode": ("drivemode", "capturemode"),
    "isoauto": ("isoauto", "autoiso"),
    "exposurecompensation2": ("exposurecompensation2", "exposurecompensation"),
}
# Every alternative name -> its logical (WRITABLE) setting; these are writable too.
_LOGICAL_OF: dict[str, str] = {
    alt: logical for logical, names in SETTING_NAMES.items() for alt in names
}


def logical_name(name: str) -> str:
    """Alias or any body's widget name -> the logical setting name (``exposuremetermode`` ->
    ``meteringmode``); other names are returned resolved but unchanged."""
    w = resolve_name(name)
    return _LOGICAL_OF.get(w, w)


def _rank(name: str) -> int:
    """Write order of a widget name (logical or an alternative name)."""
    return _ORDER.get(name, _ORDER.get(_LOGICAL_OF.get(name, ""), len(_ORDER)))


def _is_writable_name(name: str) -> bool:
    return name in _ORDER or name in _LOGICAL_OF


@dataclass(frozen=True, slots=True)
class SettingView:
    name: str
    alias: str | None
    label: str
    path: str
    type: ConfigType
    value: SettingValue | None
    readonly: bool
    choices: tuple[str, ...]
    range: ConfigRange | None
    writable: bool


@dataclass(frozen=True, slots=True)
class SkippedSetting:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class SetManyResult:
    applied: list[SettingView]
    skipped: list[SkippedSetting] = field(default_factory=list)


def resolve_name(name: str) -> str:
    """Friendly alias (``aperture``) or widget name -> widget name."""
    return ALIASES.get(name, name)


def _fail(widget: ConfigWidget, value: object, why: str) -> SettingInvalid:
    return SettingInvalid(
        f"Invalid value {value!r} for {widget.name!r}: {why}",
        details={"name": widget.name, "value": value, "type": str(widget.type)},
    )


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


_FRACTION = re.compile(r"^(-?\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)$")


def _parse_num(v: object) -> float | None:
    """Number inside values like "+1", "f/2.8", "1/250", "0.0040s", "-0.667"; else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if not isinstance(v, str):
        return None
    t = v.strip().lower().replace(" ", "")
    if t.startswith(("f/", "f")):
        t = t[2:] if t.startswith("f/") else t[1:]
    t = t.removeprefix("+").removesuffix("s")
    m = _FRACTION.match(t)
    try:
        if m:
            den = float(m.group(2))
            return float(m.group(1)) / den if den else None
        n = float(t)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def _nearby(widget: ConfigWidget, value: object, limit: int = 5) -> list[str]:
    n = _parse_num(value)
    if n is not None:
        scored = [(abs(p - n), c) for c in widget.choices if (p := _parse_num(c)) is not None]
        if scored:
            return [c for _, c in sorted(scored)[:limit]]
    return difflib.get_close_matches(str(value), widget.choices, n=limit, cutoff=0.0)


def _numeric_matches(widget: ConfigWidget, n: float) -> list[str]:
    """Choices numerically equal to ``n``. Integers must match exactly (ISO 999 is not 1000);
    a non-integer only bridges rounding: the nearest choice within 5% that is also closer than
    half the gap to the next-nearest choice (a midway value is ambiguous, so no match)."""
    nums = [(p, c) for c in widget.choices if (p := _parse_num(c)) is not None]
    if n.is_integer():
        return [c for p, c in nums if math.isclose(p, n, rel_tol=0, abs_tol=1e-9)]
    nums.sort(key=lambda pc: abs(pc[0] - n))
    if not nums:
        return []
    d1 = abs(nums[0][0] - n)
    if d1 > 0.05 * max(abs(n), abs(nums[0][0])):
        return []
    if len(nums) > 1 and not d1 < abs(nums[0][0] - nums[1][0]) / 2:
        return []  # ambiguous (duplicates, or midway between two choices)
    return [nums[0][1]]


def _match_choice(widget: ConfigWidget, value: object) -> str:
    """The camera's canonical choice string for ``value``: exact, then numeric equality within
    a small tolerance ("+1" == "1", "2.8" == "f/2.8", "1/250" == "0.0040s"), then
    case-insensitive. Ambiguous or no match raises SettingInvalid listing nearby choices."""
    choices = widget.choices
    cands = [str(value)]
    if isinstance(value, float) and value.is_integer():
        cands.append(str(int(value)))
    for c in cands:
        if c in choices:
            return c
    found: list[str] = []
    n = _parse_num(value)
    if n is not None:
        found = _numeric_matches(widget, n)
    if not found:
        low = str(value).strip().lower()
        found = [c for c in choices if c.lower() == low]
    if len(found) == 1:
        return found[0]
    err = _fail(widget, value, "ambiguous" if found else "not one of the available choices")
    err.details["nearby"] = found or _nearby(widget, value)
    raise err


def validate_value(widget: ConfigWidget, value: object) -> SettingValue:
    """Check ``value`` against the widget type and return the normalised value to send."""
    t = widget.type
    if t in (ConfigType.RADIO, ConfigType.MENU):
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise _fail(widget, value, "string or number required")
        return _match_choice(widget, value)
    if t is ConfigType.RANGE:
        if not _is_num(value):
            raise _fail(widget, value, "number required")
        v = float(value)  # type: ignore[arg-type]
        if not math.isfinite(v):
            raise _fail(widget, value, "finite number required")
        r = widget.range
        if r is not None:
            if not r.min <= v <= r.max:
                raise _fail(widget, value, f"must be within [{r.min}, {r.max}]")
            if r.step > 0:
                n = (v - r.min) / r.step
                if abs(n - round(n)) > 1e-6:
                    raise _fail(widget, value, f"must be a multiple of {r.step} from {r.min}")
        return v
    if t is ConfigType.TOGGLE:
        if isinstance(value, bool):
            return value
        raise _fail(widget, value, "boolean required")
    if t is ConfigType.DATE:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                raise _fail(widget, value, "ISO 8601 date or integer epoch required") from None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp())
        raise _fail(widget, value, "integer epoch or ISO 8601 string required")
    if t is ConfigType.TEXT:
        if isinstance(value, str):
            return value
        raise _fail(widget, value, "string required")
    raise _fail(widget, value, f"widget of type {t} cannot be set")


class SettingsService:
    def __init__(self, camera: CameraService) -> None:
        self._cam = camera

    # views ----------------------------------------------------------------------------
    @staticmethod
    def _view(w: ConfigWidget, name: str | None = None) -> SettingView:
        """``name`` overrides the widget name (the logical name the caller asked for)."""
        shown = name or w.name
        return SettingView(
            name=shown,
            alias=_ALIAS_OF.get(shown),
            label=w.label,
            path=w.path,
            type=w.type,
            value=w.value,
            readonly=w.readonly,
            choices=w.choices,
            range=w.range,
            writable=_is_writable_name(w.name) and not w.readonly and w.type != ConfigType.UNKNOWN,
        )

    @staticmethod
    def _leaves(tree: Any) -> list[ConfigWidget]:
        out: list[ConfigWidget] = []
        for w in tree:
            if w.children:
                out.extend(SettingsService._leaves(w.children))
            if w.type != ConfigType.SECTION:
                out.append(w)
        return out

    # reads ----------------------------------------------------------------------------
    @staticmethod
    def resolve_name(name: str) -> str:
        return resolve_name(name)

    @staticmethod
    def _common(leaves: list[ConfigWidget]) -> list[SettingView]:
        """COMMON settings under their logical names, each backed by this body's own widget."""
        by_name = {w.name: w for w in leaves}
        out: list[SettingView] = []
        for n in COMMON:
            w = next((by_name[c] for c in SETTING_NAMES.get(n, (n,)) if c in by_name), None)
            if w is not None:
                out.append(SettingsService._view(w, n))
        return out

    async def _actual(self, name: str) -> str:
        """The widget name for ``name`` on the connected body (aliases resolved and cached)."""
        logical = resolve_name(name)
        names = SETTING_NAMES.get(logical)
        if names is None:
            return logical
        return await self._cam.resolve_setting(logical, names)

    async def list_settings(self, group: Literal["common", "all"] = "common") -> list[SettingView]:
        leaves = self._leaves(await self._cam.list_settings())
        if group == "all":
            return [self._view(w) for w in leaves]
        return self._common(leaves)

    async def get(self, name: str, *, fresh: bool = False) -> SettingView:
        """One setting. ``fresh`` re-reads just that widget from the camera (one get_config)
        and announces SETTING_CHANGED if it differs from what was cached."""
        logical = resolve_name(name)
        actual = await self._actual(name)
        if fresh:
            before = self._cam.cached_setting(actual)
            w = await self._cam.refresh_setting(actual)
            if before is None or before.value != w.value:
                self._cam.bus.publish(EventType.SETTING_CHANGED, {"name": w.name, "value": w.value})
        else:
            w = await self._cam.get_setting(actual)
        return self._view(w, logical if logical in SETTING_NAMES else None)

    async def refresh(self, group: Literal["common", "all"] = "common") -> list[SettingView]:
        """Drop the settings cache and re-read the full config tree from the camera."""
        self._cam.invalidate_settings()
        leaves = self._leaves(await self._cam.list_settings(refresh=True))
        if group == "all":
            return [self._view(w) for w in leaves]
        return self._common(leaves)

    # writes ---------------------------------------------------------------------------
    async def prepare(self, name: str, value: object) -> tuple[str, SettingValue]:
        wname = await self._actual(name)
        widget = await self._cam.get_setting(wname)
        if widget.readonly:
            raise SettingNotAllowed(f"Setting {wname!r} is read-only", details={"name": wname})
        if not _is_writable_name(wname):
            raise SettingNotAllowed(
                f"Setting {wname!r} cannot be changed through the generic settings API",
                details={"name": wname},
            )
        return wname, validate_value(widget, value)

    async def set(self, name: str, value: object, *, owner: str | None = None) -> SettingView:
        wname, v = await self.prepare(name, value)
        logical = resolve_name(name)
        shown = logical if logical in SETTING_NAMES else None
        return self._view(await self._cam.set_setting(wname, v, owner=owner), shown)

    async def set_many(
        self,
        values: dict[str, Any],
        *,
        owner: str | None = None,
        continue_on_error: bool = False,
        skip_unusable: bool = False,
    ) -> SetManyResult:
        """Validate all first, then apply in WRITABLE order. If the camera fails mid-way the
        raised error's ``details`` carry ``applied`` (names) and ``failed`` (name); with
        ``continue_on_error`` every setting is attempted and the first error raised at the end."""
        prepared: dict[str, SettingValue] = {}
        skipped: list[SkippedSetting] = []
        for name, value in values.items():
            try:
                wname, v = await self.prepare(name, value)
            except (SettingNotAllowed, SettingNotFound) as e:
                if not skip_unusable:
                    raise
                skipped.append(SkippedSetting(name=name, reason=e.message))
                continue
            if wname in prepared:
                raise SettingInvalid(
                    f"Setting {wname!r} given more than once", details={"name": wname}
                )
            prepared[wname] = v
        applied: list[SettingView] = []
        first_err: AppError | None = None
        for wname in sorted(prepared, key=_rank):
            try:
                widget = await self._cam.set_setting(wname, prepared[wname], owner=owner)
            except AppError as e:
                err = type(e)(
                    e.message,
                    details={
                        **e.details,
                        "applied": [a.name for a in applied],
                        "failed": wname,
                    },
                    recoverable=e.recoverable,
                )
                if not continue_on_error:
                    raise err from e
                first_err = first_err or err
                continue
            applied.append(self._view(widget))
        if first_err is not None:
            raise first_err
        return SetManyResult(applied, skipped)

    # snapshot / restore ----------------------------------------------------------------
    async def snapshot(
        self, names: list[str] | tuple[str, ...], *, skip_readonly: bool = False
    ) -> dict[str, SettingValue]:
        """The camera's CURRENT values (fresh read, not the cache), keyed by widget name.
        ``skip_readonly`` leaves out widgets the body currently reports read-only."""
        out: dict[str, SettingValue] = {}
        for n in names:  # one get_config per widget; never the whole tree
            w = await self._cam.refresh_setting(await self._actual(n))
            if skip_readonly and w.readonly:
                continue
            if w.value is None:
                raise SettingNotFound(f"Setting {w.name!r} has no value", details={"name": w.name})
            out[w.name] = w.value
        return out

    async def restore(
        self, snapshot: dict[str, SettingValue], *, owner: str | None = None
    ) -> SetManyResult:
        """Put snapshot values back. Best effort: every setting is attempted."""
        return await self.set_many(dict(snapshot), owner=owner, continue_on_error=True)
