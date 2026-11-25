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
        ("format-usb",),
        ("format-usb", "sda", "8:0", "1024", "5"),
        ("format-usb", "../sda", "8:0", "1024", "5", "exfat"),
        ("format-usb", "sda", "8-0", "1024", "5", "exfat"),
        ("format-usb", "sda", "8:0", "1e3", "5", "exfat"),
        ("format-usb", "sda", "8:0", "1024", "x", "exfat"),
        ("format-usb", "sda", "8:0", "1024", "5", "xfs"),
        ("format-usb", "sda", "8:0", "1024", "5", "exfat", "a;b"),
        ("format-usb", "sda", "8:0", "1024", "5", "exfat", "-L"),
        ("format-usb", "sda", "8:0", "1024", "5", "fat32", "A" * 12),
        ("format-usb", "sda", "8:0", "1024", "5", "ext4", "A" * 17),
        ("format-usb", "sda", "8:0", "1024", "5", "exfat", "a", "extra"),
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


def test_helper_is_sourceable_without_running_and_only_usb_entry_point_formats() -> None:
    r = subprocess.run(
        ["sh", "-c", f". {HELPER} && command -v format_disk"],
        capture_output=True, text=True, timeout=20, cwd="/",
    )  # fmt: skip
    assert r.returncode == 0 and "format_disk" in r.stdout and "usage" not in r.stderr
    assert "fmt_is_usb" in TEXT[TEXT.index("cmd_format_usb()") :]
    main = TEXT[TEXT.index("main() {") : TEXT.index("# Run only when")]
    assert "format_disk" not in main.replace("cmd_format_usb", "")


def _fn(name: str) -> str:
    start = TEXT.index(f"{name}() {{")
    return TEXT[start : TEXT.index("\n}\n", start)]


def test_format_hardening_is_present() -> None:
    fd = _fn("format_disk")
    assert "LC_ALL=C" in TEXT.split("main() {")[0]
    # destructive steps never swallow failure
    for line in fd.splitlines():
        if re.search(r"wipefs|sfdisk|mkfs|fmt_run", line):
            assert "|| true" not in line
    # lock, identity (diskseq), holders and claim probe all come before the first wipefs
    first_write = fd.index("fmt_run wipefs")
    for step in ("flock -n 9", "fmt_identity", "fmt_holders", "fmt_claim"):
        assert fd.index(step) < first_write, step
    assert "diskseq" in _fn("fmt_identity") and "O_EXCL" in _fn("fmt_claim")
    assert "holders/" in _fn("fmt_holders")
    # fat32 over 2 TiB refused; new partition must be the single partition 1 at sector 2048
    assert "fat32" in fd and "2 TB" in fd
    assert "2048" in _fn("fmt_pick_part") and '"$partition" = 1' in _fn("fmt_pick_part")
    # destructive children run in the background so TERM is handled promptly
    assert "wait" in _fn("fmt_run") and "&" in _fn("fmt_run")


def test_mount_and_fsck_refuse_a_disk_being_formatted() -> None:
    assert "fmt_locked" in _fn("find_usb")
    assert "diskseq" in _fn("scan") and '"diskseq":%s' in _fn("cmd_list_usb")


def test_usb_check_requires_usb_bus_path_and_subsystem() -> None:
    f = _fn("fmt_is_usb")
    assert "usb[0-9]" in f and "subsystem" in f
