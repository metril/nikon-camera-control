"""Validation and static hardening checks of docker/ncc-storage (no mounts, no root)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "docker" / "ncc-storage"
LONG = "a" * 65


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(HELPER), *args], capture_output=True, text=True, timeout=20)


def test_syntax() -> None:
    assert subprocess.run(["sh", "-n", str(HELPER)]).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck() -> None:
    assert subprocess.run(["shellcheck", str(HELPER)]).returncode == 0


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("bogus",),
        ("list-usb", "extra"),
        ("mount-usb",),
        ("mount-usb", "../etc"),
        ("mount-usb", "a b"),
        ("mount-usb", "-x;rm"),
        ("mount-usb", LONG),
        ("mount-usb", "a\nb"),
        ("mount-smb", "x"),
        ("mount-smb", "Bad", "//h/s"),
        ("mount-smb", "-x", "//h/s"),
        ("mount-smb", "../x", "//h/s"),
        ("mount-smb", "ok", "/h/s"),
        ("mount-smb", "ok", "//h/s,extra=1"),
        ("mount-smb", "ok", "//h"),
        ("mount-smb", "ok", "//h/s\nx"),
        ("mount-smb", "ok", "//h s/x"),
        ("unmount",),
        ("unmount", "../x"),
        ("unmount", "usb-"),
        ("unmount", "nfs-abc"),
        ("unmount", "usb-abc", "--force"),
        ("unmount", "usb-abc", "--lazy", "x"),
        ("fsck",),
        ("fsck", "a/b"),
        ("fsck", LONG),
    ],
)
def test_rejects_bad_args(args: tuple[str, ...]) -> None:
    r = run(*args)
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr


TEXT = HELPER.read_text()


def test_every_mount_option_set_forbids_symlink_following() -> None:
    sets = re.findall(r"^\s*(?:base|opts)=(\S+)", TEXT, re.M)
    assert sets
    # usb options derive from a base that has nosymfollow; the cifs base has it explicitly
    for s in sets:
        assert s.startswith("$base") or "nosymfollow" in s
    assert "nosymfollow" in re.search(r"^\s*base=nosuid\S*", TEXT, re.M).group(0)  # type: ignore[union-attr]


def test_posix_root_refuses_symlink_and_chowns_without_following() -> None:
    assert '[ -L "$mp/ncc" ]' in TEXT
    assert "chown -h 1000:1000" in TEXT
    assert not re.search(r"chown (?!-h)\S* ?1000", TEXT)


def test_private_state_is_root_only_and_not_in_app_writable_run_dir() -> None:
    assert "RUN_DIR=/run/ncc-root" in TEXT
    assert "/run/ncc/" not in TEXT and "RUN_DIR=/run/ncc\n" not in TEXT
    assert "mktemp" in TEXT and "creds=$(cat)" in TEXT  # credentials arrive on stdin


def test_smb_encryption_fallback_is_narrow_and_reported() -> None:
    assert '"encrypted"' in TEXT
    fallback = TEXT[TEXT.index('*"error(95)"*') :].split(";;", 1)[0]
    assert "13" not in fallback and "ermission" not in fallback


def test_list_usb_reports_root_for_mounted_posix_drives() -> None:
    assert '"root":%s' in TEXT and "is_posix" in TEXT
