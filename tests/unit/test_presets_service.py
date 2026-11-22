import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.api.schemas.presets import (
    BracketPresetIn,
    PresetImportIn,
    SettingsPresetIn,
)
from backend.api.schemas.timelapse import QuickBracketing
from backend.core.errors import InvalidState, PresetNotFound, SettingNotAllowed
from backend.services.presets import FILE_NAME, PresetService


def leftovers(d: Path, pattern: str) -> list[Path]:
    return list(d.glob(pattern))


def svc(d: Path) -> PresetService:
    return PresetService(d, MagicMock())


def sp(name: str = "Night", **v: object) -> SettingsPresetIn:
    return SettingsPresetIn(name=name, values=v or {"iso": 3200})  # type: ignore[arg-type]


async def test_persists_across_instances(tmp_path: Path) -> None:
    p = await svc(tmp_path).create(sp())
    again = await svc(tmp_path).get(p.id)
    assert again.name == "Night" and again.created is not None
    assert not leftovers(tmp_path, "*.tmp")


async def test_aliases_normalised_and_unwritable_rejected(tmp_path: Path) -> None:
    p = await svc(tmp_path).create(sp("a", aperture="f/2.8"))
    assert p.kind == "settings" and "f-number" in p.values
    with pytest.raises(SettingNotAllowed):
        await svc(tmp_path).create(sp("b", capturetarget="Memory card"))


async def test_name_unique_per_kind_case_insensitive(tmp_path: Path) -> None:
    s = svc(tmp_path)
    await s.create(sp("Night"))
    with pytest.raises(InvalidState):
        await s.create(sp("night"))
    b = BracketPresetIn(name="Night", bracketing=QuickBracketing(iso=["100", "200"]))
    await s.create(b)  # other kind: fine
    with pytest.raises(InvalidState):  # clashes with a built-in bracket name
        await s.create(BracketPresetIn(name="exposure_3", bracketing=b.bracketing))


async def test_corrupt_file_moved_aside_not_fatal(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_text("{not json")
    s = svc(tmp_path)
    out = await s.list("settings")
    assert out.items == [] and out.warning and "moved" in out.warning
    assert leftovers(tmp_path, f"{FILE_NAME}.corrupt-*")
    await s.create(sp())  # usable afterwards
    assert json.loads((tmp_path / FILE_NAME).read_text())["schema_version"] == 1


async def test_bad_items_skipped_on_load(tmp_path: Path) -> None:
    good = await svc(tmp_path).create(sp())
    doc = json.loads((tmp_path / FILE_NAME).read_text())
    doc["presets"].append({"id": "x", "kind": "nope"})
    (tmp_path / FILE_NAME).write_text(json.dumps(doc))
    out = await svc(tmp_path).list("settings")
    assert [p.id for p in out.items] == [good.id] and "skipped" in (out.warning or "")


async def test_get_unknown(tmp_path: Path) -> None:
    with pytest.raises(PresetNotFound):
        await svc(tmp_path).get("nope")


async def test_import_replace_and_merge(tmp_path: Path) -> None:
    s = svc(tmp_path)
    await s.create(sp("old"))
    doc = PresetImportIn(
        replace=True,
        presets=[
            {"kind": "settings", "name": "new", "values": {"iso": 100}},
            {"kind": "settings", "name": "bad", "values": {}},
            {"kind": "settings", "name": "new", "values": {"iso": 200}},
        ],
    )
    r = await s.import_(doc)
    assert (r.created, r.failed, r.skipped) == (1, 1, 1)
    assert [p.name for p in (await s.list("settings")).items] == ["new"]
