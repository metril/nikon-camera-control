"""Bracket step generation (pure, no camera): quick setup, built-in presets, timing maths.

Quick-setup semantics are ported unchanged from the legacy handler: ``sequence`` concatenates
the enabled types in the order exposure, iso, aperture, shutter; ``paired`` zips them by index
up to the longest list (shorter lists simply stop contributing).
"""

from __future__ import annotations

from backend.api.schemas.timelapse import (
    MAX_STEPS,
    MIN_STEPS,
    BracketStep,
    PresetOut,
    QuickBracketing,
)
from backend.core.errors import ConfigInvalid
from backend.services.settings import resolve_name

# Time model used for the minimum interval of a bracket set.
# D500-UNVERIFIED: these are estimates, not measurements from a real body. The runner measures
# the real set duration and warns once if it exceeds the interval (``interval_too_short``).
SHOT_ESTIMATE_S = 1.0  # capture + download of one frame
SETTLE_S = 0.3  # wait after applying a step's settings (also used by the runner)
RESTORE_S = 0.5  # restoring the original values after the set


def _step(name: str, value: str, label: str) -> BracketStep:
    return BracketStep(settings={name: value}, label=label)


def _ev_label(v: str) -> str:
    return f"{float(v):+g} EV" if float(v) else "0 EV"


def _ev(values: list[str]) -> list[BracketStep]:
    # Values are camera-neutral decimals ("1", "-0.667"); they are resolved to the camera's
    # own choice strings through ``SettingsService.prepare`` before any shot is taken.
    return [_step("exposurecompensation", v, _ev_label(v)) for v in values]


def _iso(values: list[str]) -> list[BracketStep]:
    return [_step("iso", v, f"ISO {v}") for v in values]


def generate_quick(q: QuickBracketing) -> list[BracketStep]:
    """Steps for a quick setup (legacy ``QuickBracketSetup.generate_steps``)."""
    types: list[tuple[str, list[str], str]] = []  # (setting, values, paired label prefix)
    for setting, values, prefix in (
        ("exposurecompensation", q.exposure, "EV"),
        ("iso", q.iso, "ISO "),
        ("aperture", q.aperture, ""),
        ("shutterspeed", q.shutter, ""),
    ):
        if values:
            types.append((setting, list(values), prefix))
    steps: list[BracketStep] = []
    if q.combine_mode == "sequence":
        for setting, values, _ in types:
            for v in values:
                if setting == "exposurecompensation":
                    label = f"{v} EV"
                elif setting == "iso":
                    label = f"ISO {v}"
                else:
                    label = v
                steps.append(BracketStep(settings={setting: v}, label=label))
    elif types:
        for i in range(max(len(vals) for _, vals, _ in types)):
            settings: dict[str, str | int | float | bool] = {}
            labels: list[str] = []
            for setting, values, prefix in types:
                if i < len(values):
                    settings[setting] = values[i]
                    labels.append(f"{prefix}{values[i]}")
            if settings:
                steps.append(BracketStep(settings=settings, label=" / ".join(labels)))
    return steps


def _p(name: str, description: str, steps: list[BracketStep]) -> tuple[str, PresetOut]:
    return name, PresetOut(name=name, description=description, steps=steps)


_EV5 = ["-2", "-1", "0", "1", "2"]
PRESETS: dict[str, PresetOut] = dict(
    [
        _p("exposure_3", "3 shots, -2/0/+2 EV", _ev(["-2", "0", "2"])),
        _p("exposure_5", "5 shots, -2 to +2 EV", _ev(_EV5)),
        _p("exposure_7", "7 shots, -3 to +3 EV", _ev(["-3", "-2", "-1", "0", "1", "2", "3"])),
        _p("iso_3", "3 shots, ISO 200/800/3200", _iso(["200", "800", "3200"])),
        _p("hdr_3shot", "HDR: -2/0/+2 EV", _ev(["-2", "0", "2"])),
        _p("hdr_5shot", "HDR: -2 to +2 EV", _ev(_EV5)),
        _p(
            "hdr_iso_combo",
            "HDR plus a high-ISO frame",
            [
                BracketStep(
                    settings={"exposurecompensation": e, "iso": i},
                    label=f"{_ev_label(e)} / ISO {i}",
                )
                for e, i in (("-2", "100"), ("0", "100"), ("2", "100"), ("0", "800"))
            ],
        ),
        _p("astro_stack", "ISO 1600/3200/6400", _iso(["1600", "3200", "6400"])),
        _p(
            "aperture_sweep",
            "f/2.8, f/5.6, f/11",
            [_step("aperture", f"f/{v}", f"f/{v}") for v in ("2.8", "5.6", "11")],
        ),
    ]
)


def preset_steps(name: str) -> list[BracketStep]:
    p = PRESETS.get(name)
    if p is None:
        raise ConfigInvalid(
            f"Unknown bracket preset {name!r}", details={"available": sorted(PRESETS)}
        )
    return [s.model_copy(deep=True) for s in p.steps]


def normalise_steps(steps: list[BracketStep]) -> list[BracketStep]:
    """Resolve setting aliases to widget names; enforce 2-15 steps, each with settings."""
    if not MIN_STEPS <= len(steps) <= MAX_STEPS:
        raise ConfigInvalid(
            f"A bracket needs {MIN_STEPS}-{MAX_STEPS} steps, got {len(steps)}",
            details={"steps": len(steps)},
        )
    out: list[BracketStep] = []
    for i, s in enumerate(steps):
        if not s.settings:
            raise ConfigInvalid(f"Bracket step {i + 1} has no settings", details={"step": i})
        settings = {resolve_name(k): v for k, v in s.settings.items()}
        if len(settings) != len(s.settings):
            raise ConfigInvalid(f"Bracket step {i + 1} sets a setting twice", details={"step": i})
        out.append(BracketStep(settings=settings, label=s.label, delay_ms=s.delay_ms))
    return out


def touched_settings(steps: list[BracketStep]) -> list[str]:
    """Every setting name the steps touch, in first-use order."""
    seen: dict[str, None] = {}
    for s in steps:
        for k in s.settings:
            seen.setdefault(k, None)
    return list(seen)


def min_set_duration(steps: list[BracketStep]) -> float:
    """Estimated seconds one set needs (no bracketing: one shot)."""
    if not steps:
        return SHOT_ESTIMATE_S
    return sum(SHOT_ESTIMATE_S + SETTLE_S + s.delay_ms / 1000 for s in steps) + RESTORE_S


def min_interval(steps: list[BracketStep], floor_s: float) -> float:
    """Smallest interval that can fit the set (never below the configured floor)."""
    return round(max(floor_s, min_set_duration(steps) if steps else 0.0), 2)
