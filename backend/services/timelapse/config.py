"""Time-lapse config validation: normalise, resolve bracket steps, check limits and estimate."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.api.schemas.timelapse import (
    BracketStep,
    Estimate,
    NoBracketing,
    PresetBracketing,
    ResolvedStep,
    StepsBracketing,
    TimelapseConfigResult,
    TimelapseSetup,
)
from backend.core.config_store import TimelapseConfig as TimelapseLimits
from backend.core.errors import AppError, ConfigInvalid
from backend.services.settings import SettingsService
from backend.services.timelapse.brackets import (
    generate_quick,
    min_interval,
    normalise_steps,
    preset_steps,
)

DEFAULT_SHOT_BYTES = 25_000_000


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    config: TimelapseSetup
    steps: list[BracketStep]  # empty = single shot per interval
    total_sets: int
    min_interval_s: float
    shot_bytes: int

    @property
    def shots_per_set(self) -> int:
        return max(1, len(self.steps))

    @property
    def planned_shots(self) -> int:
        return self.total_sets * self.shots_per_set

    def estimate(self) -> Estimate:
        c = self.config
        dur = (
            float(c.duration_s)
            if c.duration_s is not None
            else (self.total_sets - 1) * c.interval_s
        )
        return Estimate(
            total_sets=self.total_sets,
            shots_per_set=self.shots_per_set,
            total_shots=self.planned_shots,
            duration_s=dur,
            disk_bytes=self.planned_shots * self.shot_bytes,
        )

    def result(self) -> TimelapseConfigResult:
        return TimelapseConfigResult(
            config=self.config,
            resolved_steps=[
                ResolvedStep(index=i, label=s.label, settings=s.settings, delay_ms=s.delay_ms)
                for i, s in enumerate(self.steps)
            ],
            estimate=self.estimate(),
            min_interval_s=self.min_interval_s,
        )


def shot_bytes_for(image_quality: str | None) -> int:
    """Rough bytes per shot from the camera's image quality choice."""
    if not image_quality:
        return DEFAULT_SHOT_BYTES
    q = image_quality.upper()
    if "NEF" in q or "RAW" in q:
        return DEFAULT_SHOT_BYTES + (8_000_000 if "JPEG" in q else 0)
    return 8_000_000


def _steps_of(c: TimelapseSetup) -> list[BracketStep]:
    b = c.bracketing
    if isinstance(b, NoBracketing):
        return []
    if isinstance(b, StepsBracketing):
        return normalise_steps(list(b.steps))
    if isinstance(b, PresetBracketing):
        return normalise_steps(preset_steps(b.preset))
    steps = generate_quick(b)
    if not steps:
        raise ConfigInvalid("Quick bracketing needs at least one type with values")
    return normalise_steps(steps)


async def validate_steps(steps: list[BracketStep], settings: SettingsService) -> list[BracketStep]:
    """Check every value against the connected camera's real choices; returns normalised steps."""
    out: list[BracketStep] = []
    for i, s in enumerate(steps):
        norm: dict[str, str | int | float | bool] = {}
        for name, value in s.settings.items():
            try:
                wname, v = await settings._prepare(name, value)  # noqa: SLF001
            except AppError as e:
                raise type(e)(
                    f"Bracket step {i + 1}: {e.message}",
                    details={**e.details, "step": i},
                ) from e
            norm[wname] = v
        out.append(BracketStep(settings=norm, label=s.label, delay_ms=s.delay_ms))
    return out


async def resolve_config(
    cfg: TimelapseSetup,
    limits: TimelapseLimits,
    *,
    settings: SettingsService | None,
    shot_bytes: int = DEFAULT_SHOT_BYTES,
) -> ResolvedConfig:
    """Validate ``cfg``; ``settings`` is given only when a camera is connected."""
    steps = _steps_of(cfg)
    if settings is not None and steps:
        steps = await validate_steps(steps, settings)
    floor = min_interval(steps, limits.min_interval_s)
    if cfg.interval_s < floor:
        what = f"{len(steps)} bracket shots" if steps else "a shot"
        raise ConfigInvalid(
            f"Interval {cfg.interval_s:g}s is too short for {what}; minimum is {floor:g}s",
            details={"min_interval_s": floor, "interval_s": cfg.interval_s},
        )
    if cfg.duration_s is not None:
        duration = float(cfg.duration_s)
        total_sets = max(1, math.ceil(duration / cfg.interval_s))
    else:
        total_sets = cfg.total_frames or 1
        duration = (total_sets - 1) * cfg.interval_s
    if duration > limits.max_duration_s:
        raise ConfigInvalid(
            f"Duration {duration:g}s exceeds the maximum of {limits.max_duration_s}s",
            details={"max_duration_s": limits.max_duration_s},
        )
    if steps and isinstance(cfg.bracketing, StepsBracketing):
        norm_cfg = cfg.model_copy(update={"bracketing": StepsBracketing(steps=steps)})
    else:
        norm_cfg = cfg
    return ResolvedConfig(norm_cfg, steps, total_sets, floor, shot_bytes)
