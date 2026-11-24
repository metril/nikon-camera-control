import asyncio
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from backend.api.schemas.sessions import (
    BracketInfo,
    SessionFile,
    SessionFrame,
    SessionStatus,
    SessionVideo,
)
from backend.core.errors import InvalidState, PathNotAllowed, SessionNotFound
from backend.services.sessions import SessionStore


def frame(i: int, *, set_index: int | None = None, step: int | None = None, files=None):
    return SessionFrame(
        index=i,
        captured_at=datetime.now(UTC),
        files=files if files is not None else [SessionFile(path=f"f{i}.jpg", kind="jpeg", size=1)],
        bracket=BracketInfo(step_index=step, label=f"s{step}") if step is not None else None,
        set_index=i if set_index is None else set_index,
    )


_KINDS: tuple[tuple[str, Literal["raw", "jpeg"]], ...] = (("nef", "raw"), ("jpg", "jpeg"))


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path, fsync=False)


async def test_create_add_list_get_paginate(store: SessionStore) -> None:
    m = await store.create("Sunset", {"interval": 5}, 10)
    assert store.folder(m.id).is_dir() and m.status == SessionStatus.CONFIGURED
    for i in range(7):
        await store.add_frame(m.id, frame(i))
    got = await store.get(m.id)
    assert got.frames_captured == 7 and got.frames == [] and got.config == {"interval": 5}
    assert [fr.index for fr in await store.list_frames(m.id, 3, 2)] == [3, 4]
    assert len((await store.get(m.id, with_frames=True)).frames) == 7
    [s] = await store.list()
    assert s.id == m.id and s.frames_captured == 7 and not s.corrupt


async def test_list_newest_first(store: SessionStore) -> None:
    ticks = iter([datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)])
    store._clock = lambda: next(ticks)  # noqa: SLF001
    a = await store.create("a", {}, 1)
    b = await store.create("b", {}, 1)
    assert [s.id for s in await store.list()] == [b.id, a.id]


async def test_500_frames_fast(store: SessionStore) -> None:
    m = await store.create("big", {}, 500)
    t = time.monotonic()
    for i in range(500):
        await store.add_frame(m.id, frame(i))
    assert time.monotonic() - t < 2.0
    assert (await store.get(m.id)).frames_captured == 500
    assert len(await store.list_frames(m.id, 490, 50)) == 10


async def test_torn_last_line_ignored_and_repaired(store: SessionStore) -> None:
    m = await store.create("t", {}, 3)
    await store.add_frame(m.id, frame(0))
    await store.add_frame(m.id, frame(1))
    log = store.folder(m.id) / "frames.jsonl"
    log.write_bytes(log.read_bytes() + b'{"index": 2, "captured_at": "20')
    assert [fr.index for fr in await store.list_frames(m.id, 0, None)] == [0, 1]
    await store.add_frame(m.id, frame(2))
    assert [fr.index for fr in await store.list_frames(m.id, 0, None)] == [0, 1, 2]


async def test_corrupt_manifest_tolerated_in_listing(store: SessionStore, tmp_path: Path) -> None:
    ok = await store.create("ok", {}, 1)
    bad = store.root / "20200101-000000-abcd"
    bad.mkdir()
    (bad / "session.json").write_text("{not json")
    (store.root / "20200101-000001-abce").mkdir()  # missing manifest
    (store.root / "notasession").mkdir()
    items = await SessionStore(tmp_path, fsync=False).list()
    by = {s.id: s for s in items}
    assert len(items) == 3 and not by[ok.id].corrupt
    assert by["20200101-000000-abcd"].corrupt and by["20200101-000000-abcd"].status == "failed"
    assert by["20200101-000001-abce"].corrupt
    with pytest.raises(SessionNotFound):
        await store.get("20200101-000000-abcd")
    await store.delete("20200101-000000-abcd")


async def test_recover_interrupted(tmp_path: Path) -> None:
    s1 = SessionStore(tmp_path, fsync=False, header_flush_every=1000)
    run = await s1.create("r", {}, 5)
    paused = await s1.create("p", {}, 5)
    done = await s1.create("d", {}, 5)
    await s1.update(run.id, status="running")
    await s1.update(paused.id, status="paused")
    await s1.update(done.id, status="completed")
    for i in range(3):
        await s1.add_frame(run.id, frame(i))  # header counter not flushed
    s2 = SessionStore(tmp_path, fsync=False)
    assert sorted(s2.recover_interrupted()) == sorted([run.id, paused.id])
    g = await s2.get(run.id)
    assert g.status == "interrupted" and g.frames_captured == 3 and g.error and g.finished
    assert (await s2.get(done.id)).status == "completed"
    await s2.delete(run.id)


async def test_delete_refused_while_running(store: SessionStore) -> None:
    m = await store.create("x", {}, 1)
    await store.update(m.id, status="running")
    with pytest.raises(InvalidState):
        await store.delete(m.id)
    await store.update(m.id, status="stopped")
    await store.delete(m.id)
    assert not store.root.joinpath(m.id).exists()
    with pytest.raises(SessionNotFound):
        await store.get(m.id)
    with pytest.raises(SessionNotFound):
        await store.delete(m.id)


@pytest.mark.parametrize(
    "bad", ["../x", "..", "a/b", "20200101-000000-abcd/../..", "", "%2e%2e", "20200101-000000-ABCD"]
)
async def test_traversal_ids_rejected(store: SessionStore, bad: str) -> None:
    with pytest.raises(PathNotAllowed):
        store.folder(bad)
    with pytest.raises(PathNotAllowed):
        await store.get(bad)
    with pytest.raises(PathNotAllowed):
        await store.delete(bad)


async def test_unknown_id(store: SessionStore) -> None:
    with pytest.raises(SessionNotFound):
        await store.get("20200101-000000-abcd")
    with pytest.raises(SessionNotFound):
        await store.add_frame("20200101-000000-abcd", frame(0))


async def test_concurrent_add_frame_loses_nothing(store: SessionStore) -> None:
    m = await store.create("c", {}, 100)
    await asyncio.gather(*(store.add_frame(m.id, frame(i)) for i in range(100)))
    assert (await store.get(m.id)).frames_captured == 100
    assert sorted(fr.index for fr in await store.list_frames(m.id, 0, None)) == list(range(100))


async def test_update_validation_and_videos(store: SessionStore) -> None:
    m = await store.create("v", {}, 1)
    with pytest.raises(ValueError):
        await store.update(m.id, id="x")
    v = SessionVideo(name="a.mp4", created=datetime.now(UTC), size=5, fps=24, codec="h264")
    await store.add_video(m.id, v)
    await store.add_video(m.id, v)
    assert [x.name for x in (await store.get(m.id)).videos] == ["a.mp4"]
    assert (await store.list())[0].video_count == 1
    await store.remove_video(m.id, "a.mp4")
    assert (await store.get(m.id)).videos == []


async def test_persistence_across_stores(tmp_path: Path) -> None:
    s1 = SessionStore(tmp_path, fsync=True)
    m = await s1.create("keep", {"a": 1}, 4)
    for i in range(3):
        await s1.add_frame(m.id, frame(i))
    await s1.update(m.id, status="completed", frames_failed=1)
    s2 = SessionStore(tmp_path)
    g = await s2.get(m.id)
    assert g.name == "keep" and g.status == "completed" and g.frames_failed == 1
    assert g.frames_captured == 3 and len(await s2.list_frames(m.id, 0, None)) == 3


async def test_frame_files_ordering_and_middle_of_bracket(store: SessionStore) -> None:
    m = await store.create("b", {}, 3)
    folder = store.folder(m.id)
    idx = 0
    for set_i in range(2):
        for step in range(3):
            files: list[SessionFile] = []
            for ext, kind in _KINDS:
                name = f"s{set_i}_{step}.{ext}"
                (folder / name).write_bytes(b"x")
                files.append(SessionFile(path=name, kind=kind, size=1))
            await store.add_frame(m.id, frame(idx, set_index=set_i, step=step, files=files))
            idx += 1
    names = lambda ps: [p.name for p in ps]  # noqa: E731
    assert names(await store.frame_files(m.id)) == [
        f"s{s}_{t}.jpg" for s in range(2) for t in range(3)
    ]
    assert names(await store.frame_files(m.id, prefer="raw"))[:2] == ["s0_0.nef", "s0_1.nef"]
    assert names(await store.frame_files(m.id, middle_of_bracket=True)) == ["s0_1.jpg", "s1_1.jpg"]
    # missing file skipped; escaping path skipped
    (folder / "s0_1.jpg").unlink()
    assert names(await store.frame_files(m.id, middle_of_bracket=True)) == ["s0_1.nef", "s1_1.jpg"]


def test_file_path_validation() -> None:
    for bad in ("/etc/passwd", "../x", "a/../../x", ""):
        with pytest.raises(ValueError):
            SessionFile(path=bad)


async def test_delete_refused_while_held_by_a_render(store: SessionStore) -> None:
    m = await store.create("x", {}, 1)
    with store.hold(m.id), store.hold(m.id):
        with pytest.raises(InvalidState):
            await store.delete(m.id)
    await store.delete(m.id)  # all holds released


async def test_new_and_legacy_session_dirs_listed_with_created(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, fsync=False)
    m = await store.create("n", {}, 1)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{4}", m.id)
    (store.root / "2020-01-02-030405-abcd").mkdir()
    (store.root / "20200102-030405-abce").mkdir()
    by = {s.id: s for s in await SessionStore(tmp_path, fsync=False).list()}
    for sid in ("2020-01-02-030405-abcd", "20200102-030405-abce"):
        assert by[sid].created == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
