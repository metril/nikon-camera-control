import json
from pathlib import Path

import pytest

from backend.core.config_store import AppConfig, ConfigStore
from backend.core.errors import ConfigInvalid
from backend.core.security import verify_api_key


def test_defaults_when_missing(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "config.json")
    assert s.config == AppConfig()
    assert s.config.cors_origins == []
    assert s.config.demo_camera is False
    assert s.config.api_key_hash is None


def test_update_persists_and_reloads(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "config.json"
    s = ConfigStore(p)
    new, restart = s.update({"liveview": {"target_fps": 12}})
    assert new.liveview.target_fps == 12
    assert new.liveview.quality == "medium"  # deep merge keeps siblings
    assert restart == []
    assert ConfigStore(p).config.liveview.target_fps == 12
    assert not list(p.parent.glob("*.tmp"))


def test_restart_fields(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    _, restart = s.update({"cors_origins": ["http://x"], "demo_camera": True})
    assert restart == ["cors_origins"]


def test_invalid_patch_changes_nothing(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    with pytest.raises(ConfigInvalid) as ei:
        s.update({"video": {"crf": 999}})
    assert ei.value.http_status == 422
    with pytest.raises(ConfigInvalid):
        s.update({"bogus": 1})
    assert s.config == AppConfig()
    assert not p.exists()


def test_corrupt_file_renamed(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text("{not json")
    s = ConfigStore(p)
    assert s.config == AppConfig()
    assert not p.exists()
    assert len(list(tmp_path.glob("c.json.corrupt-*"))) == 1


def test_invalid_values_fall_back_keeping_valid_fields(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "video": {"crf": 999, "fps": 30},
                "liveview": {"target_fps": 12, "gone_field": 1},
                "removed_section": {},
                "demo_camera": True,
            }
        )
    )
    c = ConfigStore(p).config
    assert c.video.crf == 23 and c.video.fps == 30
    assert c.liveview.target_fps == 12 and c.demo_camera is True
    assert not list(tmp_path.glob("c.json.corrupt-*"))


def test_lenient_load_never_disables_auth(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    s.set_api_key_hash("a" * 64)
    p.write_text(json.dumps({"video": {"crf": 999}, "unknown_new_field": 1}))
    assert ConfigStore(p).config.api_key_hash == "a" * 64


def test_hash_not_stored_in_config_json(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    s.set_api_key_hash("b" * 64)
    s.update({"demo_camera": True})
    assert "api_key_hash" not in json.loads(p.read_text())
    assert json.loads((tmp_path / "api_key.json").read_text())["sha256"] == "b" * 64
    s.set_api_key_hash(None)
    assert not (tmp_path / "api_key.json").exists()


def test_invalid_key_file_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "api_key.json").write_text("{garbage")
    c = ConfigStore(tmp_path / "c.json").config
    assert c.api_key_hash is not None  # auth stays on
    assert not verify_api_key("x", c.api_key_hash)


def test_legacy_hash_migrated(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"demo_camera": True, "api_key_hash": "c" * 64}))
    assert ConfigStore(p).config.api_key_hash == "c" * 64
    assert json.loads((tmp_path / "api_key.json").read_text())["sha256"] == "c" * 64
    assert "api_key_hash" not in json.loads(p.read_text())
    assert ConfigStore(p).config.api_key_hash == "c" * 64


def test_reset_reports_restart_fields(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    s.update({"cors_origins": ["http://x"], "demo_camera": True})
    cfg, restart = s.reset()
    assert cfg.cors_origins == [] and restart == ["cors_origins"]
    assert s.reset()[1] == []


def test_subscribe_and_unsubscribe(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    seen: list[tuple[int, int]] = []
    unsub = s.subscribe(lambda n, o: seen.append((n.media.thumbnail_size, o.media.thumbnail_size)))
    s.update({"media": {"thumbnail_size": 300}})
    s.update({"media": {"thumbnail_size": 300}})  # no change, no notify
    assert seen == [(300, 200)]
    unsub()
    s.update({"media": {"thumbnail_size": 400}})
    assert len(seen) == 1


def test_failing_subscriber_does_not_break_update(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")

    def boom(n: AppConfig, o: AppConfig) -> None:
        raise RuntimeError

    s.subscribe(boom)
    new, _ = s.update({"demo_camera": True})
    assert new.demo_camera is True


def test_reset(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    s.update({"demo_camera": True})
    assert s.reset() == (AppConfig(), [])
    assert ConfigStore(p).config == AppConfig()


def test_initial_used_when_missing(tmp_path: Path) -> None:
    init = AppConfig(demo_camera=True)
    assert ConfigStore(tmp_path / "c.json", init).config.demo_camera is True


def test_reset_keeps_api_key_hash(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    s.set_api_key_hash("a" * 64)
    s.update({"demo_camera": True})
    assert s.reset() == (AppConfig(api_key_hash="a" * 64), [])
    assert ConfigStore(p).config.api_key_hash == "a" * 64


def test_set_api_key_hash_persists_and_notifies(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    s = ConfigStore(p)
    seen: list[str | None] = []
    s.subscribe(lambda new, old: seen.append(new.api_key_hash))
    s.set_api_key_hash("1" * 64)
    s.set_api_key_hash("1" * 64)  # no change, no notify
    assert ConfigStore(p).config.api_key_hash == "1" * 64
    s.set_api_key_hash(None)
    assert seen == ["1" * 64, None]
    assert ConfigStore(p).config.api_key_hash is None


def test_update_rejects_api_key_hash(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    with pytest.raises(ConfigInvalid):
        s.update({"api_key_hash": "x"})
    assert s.config.api_key_hash is None


def test_public_dump_and_schema(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    s.set_api_key_hash("secret")
    d = s.config.public_dump()
    assert "api_key_hash" not in d and d["api_key_set"] is True
    assert "secret" not in json.dumps(d)
    schema = s.public_schema()
    assert "api_key_hash" not in schema["properties"]
    assert schema["properties"]["api_key_set"]["readOnly"] is True
    assert "$defs" in schema


def test_new_config_fields_and_bounds(tmp_path: Path) -> None:
    cfg = AppConfig()
    assert cfg.timelapse.failure_budget == 5
    assert cfg.video.ffmpeg_path is None
    assert cfg.liveview.max_width is None
    assert cfg.camera.event_quiet_window_s == 1.0
    store = ConfigStore(tmp_path / "c.json")
    new, _ = store.update(
        {"video": {"ffmpeg_path": "/usr/bin/ffmpeg"}, "liveview": {"max_width": 640}}
    )
    assert new.video.ffmpeg_path == "/usr/bin/ffmpeg" and new.liveview.max_width == 640
    for bad in ({"timelapse": {"failure_budget": 0}}, {"timelapse": {"failure_budget": 101}}):
        with pytest.raises(ConfigInvalid):
            store.update(bad)


def test_reset_preserves_storage_section(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    store.update({"storage": {"locations": [{"id": "smb-nas", "kind": "smb", "unc": "//n/s"}]}})
    store.update({"storage": {"target_id": "smb-nas"}})
    new, _ = store.reset()
    assert new.storage.target_id == "smb-nas" and [x.id for x in new.storage.locations] == [
        "smb-nas"
    ]


def test_timezone_validated(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    assert store.config.timezone is None
    store.update({"timezone": "America/New_York"})
    assert store.config.timezone == "America/New_York"
    with pytest.raises(ConfigInvalid):
        store.update({"timezone": "Mars/Olympus"})
    assert store.config.timezone == "America/New_York"


def test_kiosk_scale_default_and_validation(tmp_path: Path) -> None:
    s = ConfigStore(tmp_path / "c.json")
    assert s.config.kiosk.scale == "auto"
    assert s.update({"kiosk": {"scale": "1.25"}})[0].kiosk.scale == "1.25"
    with pytest.raises(ConfigInvalid):
        s.update({"kiosk": {"scale": "3"}})
    assert s.config.kiosk.scale == "1.25"
