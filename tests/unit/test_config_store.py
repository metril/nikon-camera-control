import json
from pathlib import Path

import pytest

from backend.core.config_store import AppConfig, ConfigStore
from backend.core.errors import ConfigInvalid


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


def test_invalid_values_file_renamed(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"video": {"crf": 999}}))
    assert ConfigStore(p).config == AppConfig()
    assert len(list(tmp_path.glob("c.json.corrupt-*"))) == 1


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
    assert s.reset() == AppConfig()
    assert ConfigStore(p).config == AppConfig()


def test_initial_used_when_missing(tmp_path: Path) -> None:
    init = AppConfig(demo_camera=True)
    assert ConfigStore(tmp_path / "c.json", init).config.demo_camera is True
