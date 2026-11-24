import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.services import integrity


def _mk(d: Path, name: str, data: bytes) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def test_record_writes_sha256sum_format_and_sidecar(tmp_path: Path) -> None:
    a = _mk(tmp_path / "d", "a.jpg", b"aaa")
    b = _mk(tmp_path / "d", "b.jpg", b"bbb")
    integrity.record(a)
    integrity.record(b, sidecar=False)
    sums = (tmp_path / "d" / "SHA256SUMS").read_text()
    ha, hb = hashlib.sha256(b"aaa").hexdigest(), hashlib.sha256(b"bbb").hexdigest()
    assert sums == f"{ha}  a.jpg\n{hb}  b.jpg\n"
    assert (tmp_path / "d" / "a.jpg.sha256").read_text().endswith("  a.jpg\n")
    assert not (tmp_path / "d" / "b.jpg.sha256").exists()
    if shutil.which("sha256sum"):
        for args in (["-c", "SHA256SUMS"], ["-c", "a.jpg.sha256"]):
            r = subprocess.run(["sha256sum", *args], cwd=tmp_path / "d", capture_output=True)
            assert r.returncode == 0, r.stderr


def test_forget_removes_line_sidecar_and_empty_file(tmp_path: Path) -> None:
    a = _mk(tmp_path, "a.jpg", b"1")
    integrity.record(a)
    integrity.forget(a)
    assert not (tmp_path / "SHA256SUMS").exists()
    assert not (tmp_path / "a.jpg.sha256").exists()


def test_verify_reports_ok_mismatch_missing_unlisted(tmp_path: Path) -> None:
    for n in ("ok.jpg", "bad.jpg", "gone.jpg"):
        integrity.record(_mk(tmp_path / "s", n, n.encode()))
    (tmp_path / "s" / "bad.jpg").write_bytes(b"corrupted")
    (tmp_path / "s" / "gone.jpg").unlink()
    _mk(tmp_path / "s", "new.jpg", b"x")
    _mk(tmp_path / ".ncc" / "thumbs", "t.jpg", b"x")  # cache is ignored
    rep = integrity.verify(tmp_path)
    assert (rep.checked, rep.ok) == (2, 1)
    assert rep.mismatched == ["s/bad.jpg"]
    assert rep.missing == ["s/gone.jpg"]
    assert rep.unlisted == ["s/new.jpg"]


def test_verify_all_files_deleted_still_reports_missing(tmp_path: Path) -> None:
    p = _mk(tmp_path / "d", "a.jpg", b"1")
    integrity.record(p)
    p.unlink()
    assert integrity.verify(tmp_path).missing == ["d/a.jpg"]


def test_verify_sub_scope_and_cancel(tmp_path: Path) -> None:
    import threading

    integrity.record(_mk(tmp_path / "x", "a.jpg", b"1"))
    integrity.record(_mk(tmp_path / "y", "b.jpg", b"2"))
    assert integrity.verify(tmp_path, "x").checked == 1
    ev = threading.Event()
    ev.set()
    assert integrity.verify(tmp_path, cancel=ev).cancelled


@pytest.mark.parametrize(
    "name", ["SHA256SUMS", "a.jpg.sha256", "a.ncc-partial", ".hidden", "b.part", "c.mp4.part.mp4"]
)
def test_bookkeeping_names_are_aux(name: str) -> None:
    assert integrity.is_aux(name)
    assert not integrity.is_aux("IMG_0001.NEF")


def test_gnu_escaped_names_round_trip_and_sha256sum_accepts(tmp_path: Path) -> None:
    d = tmp_path / "d"
    names = ["we\\ird.jpg", "new\nline.jpg", "plain.jpg", "back\\nslash.jpg"]
    for n in names:
        integrity.record(_mk(d, n, n.encode()))
    text = (d / "SHA256SUMS").read_text()
    assert "\\\\" in text and "\\n" in text
    assert sorted(integrity.read_sums(d)) == sorted(names)
    assert integrity.verify(tmp_path).ok == len(names)
    if shutil.which("sha256sum"):
        r = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=d, capture_output=True)
        assert r.returncode == 0, r.stderr
