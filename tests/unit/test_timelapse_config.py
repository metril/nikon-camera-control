import pytest
from pydantic import ValidationError

from backend.api.schemas.timelapse import TimelapseSetup
from backend.camera.fake import FakeCamera
from backend.core.config_store import TimelapseConfig as Limits
from backend.core.errors import ConfigInvalid, SettingInvalid
from backend.services.settings import SettingsService
from backend.services.timelapse.config import resolve_config, shot_bytes_for

LIM = Limits(min_interval_s=1.0, max_duration_s=3600)


def cfg(**kw: object) -> TimelapseSetup:
    base: dict[str, object] = {"name": "t", "interval_s": 10, "total_frames": 5}
    return TimelapseSetup.model_validate(base | kw)


def test_exactly_one_of_frames_or_duration() -> None:
    with pytest.raises(ValidationError):
        cfg(duration_s=60)
    with pytest.raises(ValidationError):
        cfg(total_frames=None)
    assert cfg(total_frames=None, duration_s=60).duration_s == 60


def test_bracketing_is_a_discriminated_union_with_step_limits() -> None:
    assert cfg(bracketing={"mode": "preset", "preset": "exposure_3"}).bracketing.mode == "preset"
    with pytest.raises(ValidationError):
        cfg(bracketing={"mode": "steps", "steps": [{"settings": {"iso": "100"}}]})
    with pytest.raises(ValidationError):
        cfg(bracketing={"mode": "steps", "steps": [{"settings": {}}, {"settings": {}}]})
    with pytest.raises(ValidationError):
        cfg(bracketing={"mode": "bogus"})


async def test_estimate_and_deadline_maths() -> None:
    r = await resolve_config(cfg(), LIM, settings=None)
    e = r.estimate()
    assert (e.total_sets, e.shots_per_set, e.total_shots, e.duration_s) == (5, 1, 5, 40.0)
    assert e.disk_bytes == 5 * 25_000_000
    r = await resolve_config(
        cfg(
            total_frames=None, duration_s=35, bracketing={"mode": "preset", "preset": "exposure_3"}
        ),
        LIM,
        settings=None,
    )
    assert r.total_sets == 4 and r.estimate().total_shots == 12 and r.estimate().duration_s == 35.0
    assert [s.index for s in r.result().resolved_steps] == [0, 1, 2]


async def test_interval_must_fit_the_set_with_computed_minimum() -> None:
    with pytest.raises(ConfigInvalid) as ei:
        await resolve_config(
            cfg(interval_s=2, bracketing={"mode": "preset", "preset": "exposure_5"}),
            LIM,
            settings=None,
        )
    assert ei.value.details["min_interval_s"] > 5 and "minimum" in ei.value.message
    with pytest.raises(ConfigInvalid, match="minimum is 1s"):
        await resolve_config(cfg(interval_s=0.5), LIM, settings=None)


async def test_max_duration_enforced() -> None:
    with pytest.raises(ConfigInvalid, match="maximum"):
        await resolve_config(cfg(total_frames=None, duration_s=7200), LIM, settings=None)
    with pytest.raises(ConfigInvalid, match="maximum"):
        await resolve_config(cfg(total_frames=1000), LIM, settings=None)


async def test_quick_without_values_rejected() -> None:
    with pytest.raises(ConfigInvalid):
        await resolve_config(cfg(bracketing={"mode": "quick", "iso": []}), LIM, settings=None)


def test_shot_bytes() -> None:
    assert shot_bytes_for(None) == 25_000_000
    assert (
        shot_bytes_for("JPEG Fine") < shot_bytes_for("NEF (Raw)") < shot_bytes_for("NEF+JPEG Fine")
    )


async def test_values_checked_against_connected_camera(
    app, connected_client, fake_camera: FakeCamera
) -> None:
    svc = SettingsService(app.state.camera_service)
    ok = cfg(
        bracketing={
            "mode": "quick",
            "iso": ["100", "200"],
            "aperture": ["f/4", "f/8"],
            "combine_mode": "paired",
        }
    )
    r = await resolve_config(ok, LIM, settings=svc)
    assert r.steps[0].settings == {"iso": "100", "f-number": "f/4"}
    with pytest.raises(SettingInvalid, match="step 2"):
        await resolve_config(
            cfg(bracketing={"mode": "quick", "iso": ["100", "999"]}), LIM, settings=svc
        )
    with pytest.raises(Exception, match="read-only|cannot be changed|not found"):
        await resolve_config(
            cfg(
                bracketing={
                    "mode": "steps",
                    "steps": [{"settings": {"batterylevel": "1"}}, {"settings": {"iso": "100"}}],
                }
            ),
            LIM,
            settings=svc,
        )
