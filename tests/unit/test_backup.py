import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.services import backup, integrity


def _put(root: Path, rel: str, data: bytes, *, record: bool = True) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if record:
        integrity.record(p)
    return p


def _sync(src: Path, dst: Path, **kw: object) -> backup.SyncReport:
    return backup.sync_tree(src, dst, deep=False, sidecars=True, **kw)  # type: ignore[arg-type]


def test_sync_copies_records_hashes_and_skips_next_time(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    _put(src, "sessions/s1/f.jpg", b"F")
    _put(src, ".ncc/thumbs/t.jpg", b"cache", record=False)  # never copied
    rep = _sync(src, dst)
    assert (rep.copied, rep.skipped, rep.failed) == (2, 0, [])
    assert (dst / "sessions/s1/f.jpg").read_bytes() == b"F"
    assert not (dst / ".ncc").exists()
    assert integrity.verify(dst).ok == 2
    assert (dst / "a.jpg.sha256").exists()
    rep2 = _sync(src, dst)
    assert (rep2.copied, rep2.skipped) == (0, 2)


def test_sync_resumes_after_interrupted_copy_and_cleans_partial(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A" * 100)
    _put(src, "b.jpg", b"B" * 100)
    _sync(src, dst)
    (dst / "b.jpg").unlink()
    integrity.forget(dst / "b.jpg")
    (dst / "b.jpg.ncc-partial").write_bytes(b"BB")  # interrupted copy
    (dst / "z.ncc-partial").write_bytes(b"zz")
    rep = _sync(src, dst)
    assert (rep.copied, rep.skipped) == (1, 1)
    assert not list(dst.glob("*.ncc-partial"))
    assert (dst / "b.jpg").read_bytes() == b"B" * 100


def test_sync_replaces_changed_file_and_deep_detects_bitrot(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"AAAA")
    _sync(src, dst)
    (dst / "a.jpg").write_bytes(b"AAAX")  # same size, silent corruption
    assert _sync(src, dst).copied == 0  # fast path trusts size + listed hash
    rep = backup.sync_tree(src, dst, deep=True, sidecars=True)
    assert rep.copied == 1 and (dst / "a.jpg").read_bytes() == b"AAAA"


def test_unlisted_identical_destination_is_adopted_not_copied(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    _put(dst, "a.jpg", b"A", record=False)  # hand-copied
    rep = _sync(src, dst)
    assert (rep.copied, rep.skipped) == (0, 1)
    assert integrity.read_sums(dst)["a.jpg"] == integrity.read_sums(src)["a.jpg"]


def test_corrupted_copy_is_detected_and_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A" * 50)
    real = integrity.sha256_file
    calls = {"n": 0}

    def flaky(path: Path, cancel: threading.Event | None = None) -> str:
        if str(path).endswith(".ncc-partial"):
            calls["n"] += 1
            if calls["n"] == 1:
                return "0" * 64  # the destination read back wrong once
        return real(path, cancel)

    monkeypatch.setattr(integrity, "sha256_file", flaky)
    rep = _sync(src, dst)
    assert rep.copied == 1 and rep.failed == [] and calls["n"] == 2
    assert not list(dst.glob("*.ncc-partial"))


def test_persistently_corrupt_copy_fails_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    real = integrity.sha256_file
    monkeypatch.setattr(
        integrity,
        "sha256_file",
        lambda p, c=None: "f" * 64 if str(p).endswith(".ncc-partial") else real(p, c),
    )
    rep = _sync(src, dst)
    assert rep.copied == 0 and rep.failed and "does not match" in rep.failed[0][1]
    assert not (dst / "a.jpg").exists() and not list(dst.glob("*.ncc-partial"))


def test_source_that_disagrees_with_its_sums_is_not_propagated(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    p = _put(src, "a.jpg", b"AAAA")
    p.write_bytes(b"AAAB")  # bitrot on the source
    rep = _sync(src, dst)
    assert rep.failed and not (dst / "a.jpg").exists()


def test_file_deleted_before_copy_is_skipped(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    a = _put(src, "a.jpg", b"A")
    _put(src, "b.jpg", b"B")

    def progress(copied: int, failed: int, pending: int, current: str | None) -> None:
        if current == "a.jpg":
            a.unlink()

    rep = _sync(src, dst, progress=progress)
    assert rep.failed == [] and (dst / "b.jpg").exists() and not (dst / "a.jpg").exists()


def test_sync_stops_when_asked(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    rep = _sync(src, dst, should_stop=lambda: True)
    assert rep.cancelled and not (dst / "a.jpg").exists()


def test_offload_deletes_source_only_after_verified_copy(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "sessions/s1/a.jpg", b"A")
    _put(src, "sessions/s1/b.jpg", b"B")
    _put(src, "sessions/s2/c.jpg", b"C")
    files = backup.select_files(src, "session", session_id="s1")
    rep = backup.offload_files(files, src, dst, keep_source=False, sidecars=True)
    assert (rep.copied, rep.deleted_source, rep.failed) == (2, 2, [])
    assert not (src / "sessions/s1").exists()  # emptied dir pruned
    assert (src / "sessions/s2/c.jpg").exists()
    assert integrity.verify(dst).ok == 2


def test_offload_keep_source_and_failure_keeps_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    rep = backup.offload_files(
        backup.select_files(src, "all"), src, dst, keep_source=True, sidecars=True
    )
    assert rep.copied == 1 and rep.deleted_source == 0 and (src / "a.jpg").exists()
    # failure path
    _put(src, "b.jpg", b"B")
    real = integrity.sha256_file
    monkeypatch.setattr(
        integrity,
        "sha256_file",
        lambda p, c=None: "e" * 64 if str(p).endswith(".ncc-partial") else real(p, c),
    )
    rep = backup.offload_files([src / "b.jpg"], src, dst, keep_source=False, sidecars=True)
    assert rep.failed and (src / "b.jpg").exists() and rep.deleted_source == 0


def test_offload_older_than_scope_and_bad_session_id(tmp_path: Path) -> None:
    src = tmp_path / "src"
    old = _put(src, "old.jpg", b"1")
    _put(src, "new.jpg", b"2")
    t = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(old, (t, t))
    sel = backup.select_files(src, "older_than", before=datetime.now(UTC) - timedelta(days=1))
    assert [p.name for p in sel] == ["old.jpg"]
    with pytest.raises(ValueError):
        backup.select_files(src, "session", session_id="../x")


def test_sums_parsed_once_per_directory_and_partials_cleaned_only_where_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    for i in range(6):
        _put(src, f"s/{i}.jpg", bytes([i]))
    (dst / "other").mkdir(parents=True)
    stray = dst / "other" / "x.jpg.ncc-partial"
    stray.write_bytes(b"?")
    (dst / "s").mkdir()
    (dst / "s" / "2.jpg.ncc-partial").write_bytes(b"?")
    calls: list[Path] = []
    real = integrity.read_sums
    monkeypatch.setattr(integrity, "read_sums", lambda d: (calls.append(d), real(d))[1])
    rep = _sync(src, dst)
    assert rep.copied == 6 and not rep.failed
    assert calls.count(src / "s") == 1  # cached for the scan and the copies
    assert not (dst / "s" / "2.jpg.ncc-partial").exists()
    assert stray.exists()  # untouched directory is not walked


def test_vanished_partial_is_an_error_not_a_deleted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.jpg", b"A")
    real = integrity.sha256_file

    def hash_then_lose(p: Path, c: object = None) -> str:
        if str(p).endswith(".ncc-partial"):
            os.unlink(p)  # someone cleaned our in-flight partial
        return real(p, c)  # type: ignore[arg-type]

    monkeypatch.setattr(integrity, "sha256_file", hash_then_lose)
    rep = _sync(src, dst)
    assert rep.failed and rep.copied == 0
    rep = backup.offload_files([src / "a.jpg"], src, dst, keep_source=False, sidecars=True)
    assert rep.failed and (src / "a.jpg").exists() and rep.deleted_source == 0


def test_select_files_skips_excluded_sessions_and_fresh_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    old = _put(src, "sessions/s1/a.jpg", b"1")
    held = _put(src, "sessions/s2/b.jpg", b"2")
    fresh = _put(src, "sessions/s1/c.jpg", b"3")
    t = datetime.now(UTC).timestamp() - 60
    for p in (old, held):
        os.utime(p, (t, t))
    sel = backup.select_files(src, "all", exclude_sessions=frozenset({"s2"}), min_age_s=10)
    assert sel == [old] and fresh not in sel and held not in sel


async def test_dest_lock_is_shared_per_root(tmp_path: Path) -> None:
    assert backup.dest_lock(tmp_path) is backup.dest_lock(tmp_path)
    assert backup.dest_lock(tmp_path) is not backup.dest_lock(tmp_path / "x")
