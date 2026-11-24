import asyncio
import stat
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.core.config_store import ConfigStore
from backend.core.errors import (
    FileTooLarge,
    InvalidState,
    LocationBusy,
    MountFailed,
    NoTargetError,
)
from backend.core.events import EventBus
from backend.core.secrets import SecretStore
from backend.services.locations import LocationService, parse_mountinfo
from tests.fake_helper import FakeHelper

UUID = "ABCD-1234"
UID = f"usb-{UUID}"
PW = "p@ss-" + "word"


@dataclass
class Env:
    helper: FakeHelper
    store: ConfigStore
    secrets: SecretStore
    svc: LocationService
    busy: list[bool] = field(default_factory=lambda: [False])


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    helper = FakeHelper(tmp_path)
    store = ConfigStore(tmp_path / "data" / "config.json")
    secrets = SecretStore(tmp_path / "data" / "secrets.json")
    e = Env(helper, store, secrets, None)  # type: ignore[arg-type]
    e.svc = LocationService(
        store,
        secrets,
        EventBus(),
        runner=helper.runner,
        mount_base=helper.base,
        mountinfo=helper.mountinfo,
        ismount=helper.ismount,
        busy=lambda: e.busy[0],
    )
    yield e
    await e.svc.aclose()


def _usb(e: Env, fstype: str = "exfat") -> None:
    e.helper.plug(UUID, fstype)
    e.svc.add(kind="usb", uuid=UUID, name="SSD")


async def test_no_target_raises_until_one_is_mounted(env: Env) -> None:
    with pytest.raises(NoTargetError):
        env.svc.root()
    _usb(env)
    env.svc.set_target(UID)
    with pytest.raises(NoTargetError):  # selected but not mounted
        env.svc.root()
    await env.svc.refresh()  # detects the drive and auto-mounts it
    assert env.svc.root() == env.helper.base / UID
    assert env.svc.cache() == env.helper.base / UID / ".ncc"


async def test_ismount_guard_blocks_writes_when_mount_vanishes(env: Env) -> None:
    _usb(env)
    env.svc.set_target(UID)
    await env.svc.refresh()
    env.helper.mounted.clear()  # the mount disappeared but the app has not noticed yet
    with pytest.raises(NoTargetError):
        env.svc.root()


async def test_detected_unregistered_drive_listed_and_not_mounted(env: Env) -> None:
    env.helper.plug("FFFF-0000", "ntfs")
    await env.svc.refresh()
    [d] = env.svc.list_locations()
    assert (d.id, d.configured, d.mounted, d.supported) == ("usb-FFFF-0000", False, False, True)
    assert not [c for c in env.helper.calls if c[0] == "mount-usb"]


async def test_usb_unplug_lazily_unmounts_and_replug_remounts(env: Env) -> None:
    _usb(env)
    env.svc.set_target(UID)
    await env.svc.refresh()
    assert env.svc.get(UID).mounted
    env.helper.unplug(UUID)
    await env.svc.refresh()
    assert ["unmount", UID, "--lazy"] in env.helper.calls
    assert not env.svc.get(UID).mounted
    with pytest.raises(NoTargetError):
        env.svc.root()
    env.helper.plug(UUID)
    await env.svc.refresh()
    assert env.svc.get(UID).mounted


async def test_user_unmount_is_not_undone_by_auto_mount(env: Env) -> None:
    _usb(env)
    await env.svc.refresh()
    await env.svc.unmount(UID)
    await env.svc.refresh()
    assert not env.svc.get(UID).mounted
    await env.svc.mount(UID)
    assert env.svc.get(UID).mounted


async def test_mount_error_is_shown_verbatim(env: Env) -> None:
    _usb(env)
    env.helper.fail["mount-usb"] = "mount: wrong fs type, dirty volume"
    await env.svc.refresh()  # detects the drive; the auto-mount fails quietly
    with pytest.raises(MountFailed, match="dirty volume"):
        await env.svc.mount(UID)
    assert env.svc.get(UID).error == "mount: wrong fs type, dirty volume"


async def test_unsupported_drive_is_not_mounted(env: Env) -> None:
    env.helper.plug(UUID, "apfs", supported=False)
    env.svc.add(kind="usb", uuid=UUID)
    await env.svc.refresh()
    assert not [c for c in env.helper.calls if c[0] == "mount-usb"]
    with pytest.raises(MountFailed, match="unsupported"):
        await env.svc.mount(UID)


async def test_target_switch_and_unmount_refused_while_busy(env: Env) -> None:
    _usb(env)
    env.helper.plug("2222-2222")
    env.svc.add(kind="usb", uuid="2222-2222")
    env.svc.set_target(UID)
    await env.svc.refresh()
    env.busy[0] = True
    with pytest.raises(InvalidState):
        env.svc.set_target("usb-2222-2222")
    with pytest.raises(InvalidState):
        await env.svc.unmount(UID)
    await env.svc.unmount("usb-2222-2222")  # a non-target may always be unmounted
    env.busy[0] = False
    env.svc.set_target("usb-2222-2222")
    assert env.svc.target_id == "usb-2222-2222"


async def test_unmount_busy_exit_code_maps_to_409(env: Env) -> None:
    _usb(env)
    await env.svc.refresh()
    env.helper.busy_unmount = True
    with pytest.raises(LocationBusy):
        await env.svc.unmount(UID)
    assert env.svc.get(UID).mounted


async def test_target_cannot_be_a_backup(env: Env) -> None:
    _usb(env)
    env.helper.plug("2222-2222")
    env.svc.add(kind="usb", uuid="2222-2222")
    env.svc.set_target(UID)
    with pytest.raises(InvalidState):
        env.svc.set_backups([UID])
    env.svc.set_backups(["usb-2222-2222"])
    with pytest.raises(InvalidState):
        env.svc.set_target("usb-2222-2222")


async def test_smb_credentials_go_to_helper_on_stdin_only(env: Env) -> None:
    info = env.svc.add(
        kind="smb", name="NAS", unc="//nas/photos", username="u", password=PW, domain="D"
    )
    assert info.id == "smb-nas" and info.has_password
    await env.svc.refresh()  # auto_mount
    assert env.svc.get("smb-nas").mounted
    assert env.helper.cred_seen == [f"username=u\npassword={PW}\ndomain=D\n"]
    assert ["mount-smb", "nas", "//nas/photos"] in env.helper.calls
    assert all(PW not in " ".join(c) for c in env.helper.calls)
    assert env.svc.get("smb-nas").encrypted is True


async def test_smb_unencrypted_fallback_is_reported(env: Env) -> None:
    env.helper.encrypted = False
    env.svc.add(kind="smb", name="NAS", unc="//nas/photos")
    await env.svc.refresh()
    assert env.svc.get("smb-nas").encrypted is False


async def test_smb_unreachable_is_dropped_then_reconnected(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.svc.add(kind="smb", name="NAS", unc="//nas/photos")
    await env.svc.refresh()
    assert env.svc.get("smb-nas").mounted

    async def dead(root: Path) -> bool:
        return False

    monkeypatch.setattr(env.svc, "_healthy", dead)
    await env.svc.refresh()
    assert not env.svc.get("smb-nas").mounted
    assert ["unmount", "smb-nas", "--lazy"] in env.helper.calls
    monkeypatch.undo()
    env.svc._rt["smb-nas"].retry_at = 0.0  # backoff elapsed
    await env.svc.refresh()
    assert env.svc.get("smb-nas").mounted


async def test_smb_mount_failure_backs_off(env: Env) -> None:
    env.helper.smb_up = False
    env.svc.add(kind="smb", name="NAS", unc="//nas/photos")
    await env.svc.refresh()
    n = len([c for c in env.helper.calls if c[0] == "mount-smb"])
    await env.svc.refresh()  # inside the backoff window: no new attempt
    assert len([c for c in env.helper.calls if c[0] == "mount-smb"]) == n == 1
    assert "No route" in (env.svc.get("smb-nas").error or "")


async def test_external_unmount_is_noticed(env: Env) -> None:
    _usb(env)
    await env.svc.refresh()
    env.helper.drop_mount(UID)
    env.svc._rt[UID].user_unmounted = True  # keep auto-mount from racing the assertion
    await env.svc.refresh()
    assert not env.svc.get(UID).mounted


async def test_smb_test_connection_cleans_up(env: Env) -> None:
    ok, msg = await env.svc.test_smb("//nas/x", "u", "pw", None)
    assert ok and msg == "ok"
    assert any(c[0] == "unmount" for c in env.helper.calls)
    assert env.helper.cred_seen[0] == "username=u\npassword=pw\n"
    assert not env.secrets.path.exists() or "pw" not in env.secrets.path.read_text()
    env.helper.smb_up = False
    ok, msg = await env.svc.test_smb("//nas/x", None, None, None)
    assert not ok and "No route" in msg


def test_password_lives_only_in_secrets_file(env: Env) -> None:
    env.svc.add(kind="smb", name="NAS", unc="//nas/p", username="u", password=PW)
    assert PW not in env.store.path.read_text()
    assert stat.S_IMODE(env.secrets.path.stat().st_mode) == 0o600
    assert env.secrets.get_smb("smb-nas") == PW
    env.svc.update("smb-nas", {}, password="")
    assert env.secrets.get_smb("smb-nas") is None


async def test_remove_clears_roles_and_secret(env: Env) -> None:
    env.svc.add(kind="smb", name="NAS", unc="//nas/p", password=PW)
    env.svc.set_backups(["smb-nas"])
    await env.svc.remove("smb-nas")
    assert env.store.config.storage.locations == [] and env.store.config.storage.backup_ids == []
    assert env.secrets.get_smb("smb-nas") is None


async def test_fat32_rejects_files_over_4gib(env: Env) -> None:
    _usb(env, "vfat")
    env.svc.set_target(UID)
    await env.svc.refresh()
    env.svc.check_file_size(1024)
    env.svc.check_file_size(None)
    with pytest.raises(FileTooLarge):
        env.svc.check_file_size(5 * 1024**3)


async def test_stored_records_hash_and_triggers_backup(env: Env) -> None:
    _usb(env)
    env.svc.set_target(UID)
    await env.svc.refresh()
    hits: list[int] = []
    env.svc.on_stored = lambda: hits.append(1)
    f = env.svc.root() / "a.jpg"
    f.write_bytes(b"x")
    env.svc.stored(f)
    assert (f.parent / "SHA256SUMS").exists() and (f.parent / "a.jpg.sha256").exists() and hits
    env.store.update({"storage": {"sidecars": False}})
    g = env.svc.root() / "b.jpg"
    g.write_bytes(b"y")
    env.svc.stored(g)
    assert not (f.parent / "b.jpg.sha256").exists()


def test_parse_mountinfo_decodes_escapes() -> None:
    text = (
        "36 35 98:0 / /mnt/loc/usb-A\\040B rw - ext4 /dev/sda1 rw\n1 0 0:1 / / rw - overlay o rw\n"
    )
    assert parse_mountinfo(text) == {"/mnt/loc/usb-A B", "/"}


def test_invalid_location_rejected(env: Env) -> None:
    from backend.core.errors import ConfigInvalid

    with pytest.raises(ConfigInvalid):
        env.svc.add(kind="smb", name="x", unc="not-a-unc")
    with pytest.raises(ConfigInvalid):
        env.svc.add(kind="usb", name="x", uuid=None)


async def test_set_same_target_is_a_noop(env: Env) -> None:
    _usb(env)
    env.svc.set_target(UID)
    seen: list[str] = []
    env.svc.subscribe(lambda r, i: seen.append(r))
    env.svc.set_target(UID)
    assert seen == []


async def test_housekeeping_key_changes_only_on_new_mount(env: Env) -> None:
    _usb(env)
    env.svc.set_target(UID)
    k0 = env.svc.housekeeping_key()
    await env.svc.refresh()
    k1 = env.svc.housekeeping_key()
    assert k1 != k0
    await env.svc.refresh()
    assert env.svc.housekeeping_key() == k1
    env.svc.set_target(UID)
    assert env.svc.housekeeping_key() == k1


async def test_adopted_mount_uses_helper_root(env: Env) -> None:
    _usb(env, "ext4")
    root = env.helper.base / UID / "ncc"
    root.mkdir(parents=True)
    env.helper.usb[0].update(mounted=True, mount_path=str(env.helper.base / UID), root=str(root))
    env.helper.mounted.add(str(env.helper.base / UID))
    env.helper._sync()
    await env.svc.refresh()
    assert env.svc._rt[UID].root == root


async def test_failed_unmount_of_unplugged_drive_does_not_abort_refresh(env: Env) -> None:
    _usb(env)
    await env.svc.refresh()
    env.helper.unplug(UUID)
    env.helper.fail["unmount"] = "boom"
    await env.svc.refresh()  # must not raise
    assert env.svc._rt[UID].mounted and "boom" in (env.svc._rt[UID].error or "")


async def test_pending_probe_is_skipped_not_stacked(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from backend.services import locations as loc_mod

    monkeypatch.setattr(loc_mod, "PROBE_TIMEOUT_S", 0.05)
    gate = threading.Event()
    started: list[int] = []

    def slow(_p: Path) -> int:
        started.append(1)
        gate.wait(5)
        return 1

    key = ("x", "health")
    with pytest.raises(TimeoutError):
        await env.svc._probe(key, slow, Path("."))
    with pytest.raises(loc_mod._ProbePending):  # previous still hanging: not stacked
        await env.svc._probe(key, slow, Path("."))
    assert len(started) == 1
    gate.set()
    await asyncio.sleep(0.1)
    assert await env.svc._probe(key, lambda p: 2, Path(".")) == 2
