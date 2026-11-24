"""Storage locations (USB drives, SMB shares), the capture target and mount lifecycle.

All mounting is done by the root helper ``ncc-storage`` through ``sudo -n`` behind an
injectable async runner. A location is a plain directory once mounted; the target is the one
location that receives captures. ``LocationService`` also implements ``StorageRoot`` so
services resolve the target directory dynamically (``NoTargetError`` when unavailable).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from backend.api.schemas.common import EventType
from backend.core.config_store import ConfigStore, StorageLocation
from backend.core.errors import (
    ConfigInvalid,
    FileTooLarge,
    InvalidState,
    LocationBusy,
    LocationNotFound,
    MountFailed,
    NoTargetError,
)
from backend.core.events import EventBus
from backend.core.secrets import SecretStore
from backend.core.storage_root import CACHE_DIRNAME, FAT32_MAX_FILE
from backend.services import integrity

log = logging.getLogger(__name__)

HELPER = "/usr/local/sbin/ncc-storage"
EXIT_BUSY = 16
PROBE_TIMEOUT_S = 5.0
FAT_TYPES = frozenset({"vfat", "fat", "msdos", "fat32"})

Runner = Callable[..., Awaitable[tuple[int, str, str]]]  # (args, stdin=None)
Listener = Callable[[str, str | None], None]


async def sudo_runner(args: Sequence[str], stdin: str | None = None) -> tuple[int, str, str]:
    """Run the helper as root via sudo (the only privileged operation the app performs).
    ``stdin`` carries secrets (SMB credentials); they never touch the filesystem."""
    proc = await asyncio.create_subprocess_exec(
        "sudo",
        "-n",
        HELPER,
        *args,
        stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(None if stdin is None else stdin.encode()), timeout=180
        )
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def parse_mountinfo(text: str) -> set[str]:
    """Mount points listed in /proc/self/mountinfo (octal escapes decoded)."""
    points: set[str] = set()
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) > 4:
            points.add(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4]))
    return points


@dataclass
class _Runtime:
    present: bool = False
    mounted: bool = False
    root: Path | None = None
    fstype: str | None = None
    size: int | None = None
    free: int | None = None
    label: str | None = None
    supported: bool = True
    reason: str | None = None
    error: str | None = None
    user_unmounted: bool = False
    retry_at: float = 0.0
    backoff: float = 2.0
    encrypted: bool | None = None


@dataclass(frozen=True)
class LocationInfo:
    id: str
    kind: Literal["usb", "smb"]
    name: str
    uuid: str | None
    unc: str | None
    username: str | None
    domain: str | None
    auto_mount: bool
    configured: bool
    present: bool
    mounted: bool
    supported: bool
    reason: str | None
    fstype: str | None
    label: str | None
    size: int | None
    free: int | None
    error: str | None
    has_password: bool
    is_target: bool
    is_backup: bool
    encrypted: bool | None = None


class _ProbePending(Exception):
    """The previous probe of the same location has not finished (hung mount)."""


@dataclass
class _Detected:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    ok: bool = False


class LocationService:
    def __init__(
        self,
        store: ConfigStore,
        secrets: SecretStore,
        bus: EventBus,
        *,
        runner: Runner = sudo_runner,
        mount_base: Path = Path("/mnt/loc"),
        mountinfo: Path = Path("/proc/self/mountinfo"),
        ismount: Callable[[str], bool] = os.path.ismount,
        busy: Callable[[], bool] = lambda: False,
        poll_interval_s: float = 3.0,
        fixed_target: Path | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._bus = bus
        self._run = runner
        self._base = Path(mount_base)
        self._mountinfo = Path(mountinfo)
        self._ismount = ismount
        self.busy = busy
        self._poll = poll_interval_s
        self._fixed = Path(fixed_target) if fixed_target is not None else None
        self._rt: dict[str, _Runtime] = {}
        self._gen: dict[str, int] = {}  # bumped on every new mount of a location
        self._probe_pool = ThreadPoolExecutor(2, thread_name_prefix="loc-probe")
        self._probes: dict[tuple[str, str], asyncio.Future[Any]] = {}
        self._detected = _Detected()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._listeners: list[Listener] = []
        self.on_stored: Callable[[], None] | None = None

    # ---- StorageRoot --------------------------------------------------------------------
    @property
    def target_id(self) -> str | None:
        return "fixed" if self._fixed is not None else self._store.config.storage.target_id

    def housekeeping_key(self) -> tuple[str, int] | None:
        """(target id, mount generation): changes only when the target actually changes
        or is mounted anew."""
        tid = self.target_id
        return None if tid is None else (tid, self._gen.get(tid, 0))

    def mount_point(self, location_id: str) -> Path:
        return self._base / location_id

    def root_of(self, location_id: str) -> Path | None:
        """Mounted, guarded root of a location, or None."""
        rt = self._rt.get(location_id)
        if rt is None or not rt.mounted or rt.root is None:
            return None
        if not self._ismount(str(self.mount_point(location_id))):
            return None
        return rt.root

    def root(self) -> Path:
        if self._fixed is not None:
            return self._fixed
        tid = self._store.config.storage.target_id
        if tid is None:
            raise NoTargetError("No storage target is selected. Choose one in Settings.")
        root = self.root_of(tid)
        if root is None:
            raise NoTargetError("The storage target is not mounted.")
        return root

    target_dir = root

    def cache(self) -> Path:
        return self.root() / CACHE_DIRNAME

    def source(self) -> tuple[str, Path] | None:
        try:
            return (self.target_id or "", self.root())
        except NoTargetError:
            return None

    def destinations(self) -> list[tuple[str, Path]]:
        if self._fixed is not None:
            return []
        cfg = self._store.config.storage
        out = []
        for bid in cfg.backup_ids:
            root = self.root_of(bid)
            if root is not None and bid != cfg.target_id:
                out.append((bid, root))
        return out

    def _target_fstype(self) -> str | None:
        tid = self._store.config.storage.target_id
        rt = self._rt.get(tid) if tid else None
        return rt.fstype if rt else None

    def check_file_size(self, size: int | None) -> None:
        fs = self._target_fstype()
        if size is not None and fs in FAT_TYPES and size > FAT32_MAX_FILE:
            raise FileTooLarge(
                f"This file is {size} bytes; the target is FAT32 (4 GiB limit). "
                "Use an exFAT or ext4 target."
            )

    def stored(self, path: Path) -> None:
        """A file was finalized on the target (blocking): record its hash, queue a backup."""
        if self._fixed is not None:
            return
        try:
            integrity.record(path, sidecar=self._store.config.storage.sidecars)
        except Exception:
            log.exception("could not record hash of %s", path)
        if self.on_stored is not None:
            self.on_stored()

    # ---- events -------------------------------------------------------------------------
    def subscribe(self, cb: Listener) -> None:
        self._listeners.append(cb)

    def _changed(self, reason: str, location_id: str | None = None) -> None:
        self._bus.publish(
            EventType.LOCATIONS_CHANGED,
            {
                "reason": reason,
                "id": location_id,
                "target_id": self._store.config.storage.target_id,
            },
        )
        for cb in list(self._listeners):
            try:
                cb(reason, location_id)
            except Exception:
                log.exception("location listener failed")

    # ---- registry -----------------------------------------------------------------------
    def _cfg(self, location_id: str) -> StorageLocation:
        for loc in self._store.config.storage.locations:
            if loc.id == location_id:
                return loc
        raise LocationNotFound(details={"id": location_id})

    def _state(self, location_id: str) -> _Runtime:
        return self._rt.setdefault(location_id, _Runtime())

    def _info(self, loc: StorageLocation) -> LocationInfo:
        rt = self._state(loc.id)
        cfg = self._store.config.storage
        return LocationInfo(
            id=loc.id,
            kind=loc.kind,
            name=loc.name or rt.label or loc.id,
            uuid=loc.uuid,
            unc=loc.unc,
            username=loc.username,
            domain=loc.domain,
            auto_mount=loc.auto_mount,
            configured=True,
            present=rt.present if loc.kind == "usb" else rt.mounted or rt.error is None,
            mounted=rt.mounted,
            supported=rt.supported,
            reason=rt.reason,
            fstype=rt.fstype,
            label=rt.label,
            size=rt.size,
            free=rt.free,
            error=rt.error,
            has_password=loc.kind == "smb" and self._secrets.has_smb(loc.id),
            is_target=loc.id == cfg.target_id,
            is_backup=loc.id in cfg.backup_ids,
            encrypted=rt.encrypted if rt.mounted else None,
        )

    def list_locations(self) -> list[LocationInfo]:
        cfg = self._store.config.storage
        out = [self._info(loc) for loc in cfg.locations]
        known = {loc.uuid for loc in cfg.locations if loc.uuid}
        for item in self._detected.items.values():
            if item.get("uuid") in known:
                continue
            uuid = item.get("uuid")
            out.append(
                LocationInfo(
                    id=f"usb-{uuid}" if uuid else f"dev-{item.get('name')}",
                    kind="usb",
                    name=item.get("label") or item.get("name") or "USB drive",
                    uuid=uuid,
                    unc=None,
                    username=None,
                    domain=None,
                    auto_mount=False,
                    configured=False,
                    present=True,
                    mounted=bool(item.get("mounted")),
                    supported=bool(item.get("supported")) and bool(uuid),
                    reason=item.get("reason") or (None if uuid else "No filesystem UUID"),
                    fstype=item.get("fstype"),
                    label=item.get("label"),
                    size=item.get("size"),
                    free=None,
                    error=None,
                    has_password=False,
                    is_target=False,
                    is_backup=False,
                )
            )
        return out

    def get(self, location_id: str) -> LocationInfo:
        for info in self.list_locations():
            if info.id == location_id:
                return info
        raise LocationNotFound(details={"id": location_id})

    # ---- configuration changes ----------------------------------------------------------
    def _save_locations(self, locs: list[StorageLocation], **extra: Any) -> None:
        patch: dict[str, Any] = {"locations": [loc.model_dump(mode="json") for loc in locs]}
        patch.update(extra)
        self._store.update({"storage": patch})

    def add(
        self,
        *,
        kind: Literal["usb", "smb"],
        name: str = "",
        uuid: str | None = None,
        unc: str | None = None,
        username: str | None = None,
        domain: str | None = None,
        password: str | None = None,
        auto_mount: bool = True,
    ) -> LocationInfo:
        cfg = self._store.config.storage
        if kind == "usb":
            lid = f"usb-{uuid}"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", (name or (unc or "").rsplit("/", 1)[-1]).lower())
            slug = slug.strip("-")[:24] or "share"
            lid, n = f"smb-{slug}", 1
            ids = {loc.id for loc in cfg.locations}
            while lid in ids:
                n += 1
                lid = f"smb-{slug}-{n}"
        if any(loc.id == lid for loc in cfg.locations):
            raise InvalidState("This location is already registered", details={"id": lid})
        try:
            loc = StorageLocation(
                id=lid, kind=kind, name=name, uuid=uuid, unc=unc, username=username,
                domain=domain, auto_mount=auto_mount,
            )  # fmt: skip
        except ValueError as exc:
            raise ConfigInvalid(str(exc)) from exc
        if password:
            self._secrets.set_smb(lid, password)
        self._save_locations([*cfg.locations, loc])
        self._changed("added", lid)
        return self._info(loc)

    def update(
        self, location_id: str, changes: dict[str, Any], password: str | None = None
    ) -> LocationInfo:
        cfg = self._store.config.storage
        cur = self._cfg(location_id)
        merged = {**cur.model_dump(), **changes}
        try:
            new = StorageLocation.model_validate(merged)
        except ValueError as exc:
            raise ConfigInvalid(str(exc)) from exc
        if password is not None:
            self._secrets.set_smb(location_id, password or None)
        self._save_locations([new if loc.id == location_id else loc for loc in cfg.locations])
        self._changed("updated", location_id)
        return self._info(new)

    async def remove(self, location_id: str) -> None:
        cfg = self._store.config.storage
        self._cfg(location_id)
        if self._state(location_id).mounted:
            await self.unmount(location_id)
        self._store.update(
            {
                "storage": {
                    "target_id": None if cfg.target_id == location_id else cfg.target_id,
                    "backup_ids": [b for b in cfg.backup_ids if b != location_id],
                    "locations": [
                        loc.model_dump(mode="json")
                        for loc in cfg.locations
                        if loc.id != location_id
                    ],
                }
            }
        )
        self._secrets.set_smb(location_id, None)
        self._rt.pop(location_id, None)
        self._changed("removed", location_id)

    def set_target(self, location_id: str | None) -> None:
        cfg = self._store.config.storage
        if location_id is not None:
            self._cfg(location_id)
            if location_id in cfg.backup_ids:
                raise InvalidState("This location is a backup; remove it from the backups first")
        if location_id == cfg.target_id:
            return  # unchanged: no event, no housekeeping
        if self.busy():
            raise InvalidState("Cannot switch the target while a capture or job is active")
        self._store.update({"storage": {"target_id": location_id}})
        self._changed("target", location_id)

    def set_backups(self, ids: list[str]) -> None:
        cfg = self._store.config.storage
        for i in ids:
            self._cfg(i)
        if cfg.target_id in ids:
            raise InvalidState("The target cannot also be a backup")
        self._store.update({"storage": {"backup_ids": list(dict.fromkeys(ids))}})
        self._changed("backups", None)

    # ---- mount / unmount ----------------------------------------------------------------
    async def mount(self, location_id: str, *, user: bool = True) -> LocationInfo:
        async with self._lock:
            return await self._mount(location_id, user=user)

    async def _mount(self, location_id: str, *, user: bool) -> LocationInfo:
        loc = self._cfg(location_id)
        rt = self._state(location_id)
        if rt.mounted:
            return self._info(loc)
        if user:
            rt.user_unmounted = False
        if loc.kind == "usb":
            if not rt.present:
                raise MountFailed("The drive is not connected")
            if not rt.supported:
                raise MountFailed(rt.reason or "Unsupported filesystem")
            rc, out, err = await self._run(["mount-usb", loc.uuid or ""])
        else:
            rc, out, err = await self._mount_smb(loc, self._secrets.get_smb(loc.id))
        if rc != 0:
            rt.error = (err.strip() or out.strip() or f"mount failed (exit {rc})")[:500]
            self._changed("error", location_id)
            raise MountFailed(rt.error, details={"id": location_id})
        try:
            data = json.loads(out)
            root = Path(data["root"])
            fstype = data.get("fstype")
        except (ValueError, KeyError, TypeError) as exc:
            rt.error = "Unexpected helper output"
            raise MountFailed(rt.error) from exc
        rt.mounted, rt.root, rt.error, rt.backoff = True, root, None, 2.0
        rt.encrypted = data.get("encrypted") if isinstance(data.get("encrypted"), bool) else None
        self._gen[location_id] = self._gen.get(location_id, 0) + 1
        rt.fstype = fstype or rt.fstype
        await self._update_free(rt)
        self._changed("mounted", location_id)
        return self._info(loc)

    async def _mount_smb(self, loc: StorageLocation, password: str | None) -> tuple[int, str, str]:
        """Credentials go to the helper on stdin (cifs credentials format), never to disk."""
        slug = loc.id.removeprefix("smb-")
        fields = {"username": loc.username, "password": password, "domain": loc.domain}
        if any(v and ("\n" in v or "\r" in v) for v in fields.values()):
            return 1, "", "Credentials must not contain line breaks"
        creds = None
        if loc.username or password or loc.domain:
            lines = [f"username={loc.username or 'guest'}"]
            if password:
                lines.append(f"password={password}")
            if loc.domain:
                lines.append(f"domain={loc.domain}")
            creds = "\n".join(lines) + "\n"
        return await self._run(["mount-smb", slug, loc.unc or ""], stdin=creds)

    async def unmount(self, location_id: str, *, lazy: bool = False, user: bool = True) -> None:
        async with self._lock:
            await self._unmount(location_id, lazy=lazy, user=user)

    async def _unmount(self, location_id: str, *, lazy: bool, user: bool) -> None:
        self._cfg(location_id)
        rt = self._state(location_id)
        if user and location_id == self._store.config.storage.target_id and self.busy():
            raise InvalidState("Cannot unmount the target while a capture or job is active")
        if not rt.mounted:
            return
        rc, out, err = await self._run(["unmount", location_id, *(["--lazy"] if lazy else [])])
        if rc == EXIT_BUSY:
            raise LocationBusy("The location is in use", details={"id": location_id})
        if rc != 0:
            raise MountFailed((err.strip() or out.strip() or "unmount failed")[:500])
        rt.mounted, rt.root, rt.free, rt.encrypted = False, None, None, None
        if user:
            rt.user_unmounted = True
        self._changed("unmounted", location_id)

    async def fsck(self, location_id: str) -> tuple[int, str]:
        loc = self._cfg(location_id)
        if loc.kind != "usb":
            raise InvalidState("Only USB drives can be checked")
        async with self._lock:
            if self._state(location_id).mounted:
                raise InvalidState("Unmount the drive before checking it")
            rc, out, err = await self._run(["fsck", loc.uuid or ""])
        return rc, (out + err).strip()

    async def test_smb(
        self, unc: str, username: str | None, password: str | None, domain: str | None
    ) -> tuple[bool, str]:
        """Mount a share under a throwaway id and unmount it again."""
        slug = f"test{_secrets.token_hex(4)}"
        loc = StorageLocation(
            id=f"smb-{slug}", kind="smb", unc=unc, username=username, domain=domain
        )
        async with self._lock:
            rc, out, err = await self._mount_smb(loc, password)  # never stored
            if rc != 0:
                return False, (err.strip() or out.strip() or "mount failed")[:500]
            await self._run(["unmount", loc.id])
            return True, "ok"

    async def _probe(self, key: tuple[str, str], fn: Callable[..., Any], *args: Any) -> Any:
        """Run a blocking filesystem probe in the small dedicated pool (a hung mount can
        only stall these threads, never the default executor). A location's next probe is
        refused while its previous one is still pending."""
        prev = self._probes.get(key)
        if prev is not None and not prev.done():
            raise _ProbePending
        fut = asyncio.get_running_loop().run_in_executor(self._probe_pool, fn, *args)
        self._probes[key] = fut

        def _done(f: asyncio.Future[Any]) -> None:
            if self._probes.get(key) is f:
                del self._probes[key]
            if not f.cancelled():
                f.exception()  # mark retrieved

        fut.add_done_callback(_done)
        return await asyncio.wait_for(asyncio.shield(fut), PROBE_TIMEOUT_S)

    async def _update_free(self, rt: _Runtime) -> None:
        if rt.root is None:
            return
        try:
            du = await self._probe((str(rt.root), "free"), shutil.disk_usage, rt.root)
            rt.free, rt.size = du.free, du.total
        except _ProbePending:
            return  # previous probe still hanging: keep the last value
        except (OSError, TimeoutError):
            rt.free = None

    # ---- polling ------------------------------------------------------------------------
    async def start(self) -> None:
        if self._fixed is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._loop(), name="locations-poll")

    async def aclose(self) -> None:
        with contextlib.suppress(TimeoutError):  # a hung probe must not block shutdown
            await asyncio.wait_for(
                asyncio.to_thread(self._probe_pool.shutdown, True, cancel_futures=True), 2.0
            )
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:
                log.exception("location refresh failed")
            await asyncio.sleep(self._poll)

    def _mounted_points(self) -> set[str]:
        try:
            return parse_mountinfo(self._mountinfo.read_text())
        except OSError:
            return set()

    async def refresh(self) -> None:
        """One poll cycle: detect USB drives, reconcile mounts, auto-mount, probe SMB."""
        async with self._lock:
            await self._refresh()

    async def _refresh(self) -> None:
        try:
            rc, out, _err = await self._run(["list-usb"])
            items: Any = json.loads(out) if rc == 0 else None
        except (TimeoutError, OSError, ValueError):
            items = None
        usb_ok = isinstance(items, list)
        if usb_ok:
            self._detected = _Detected(
                {str(i.get("uuid") or i.get("name")): i for i in items if isinstance(i, dict)}, True
            )
        points = await asyncio.to_thread(self._mounted_points)
        for loc in list(self._store.config.storage.locations):
            await self._reconcile(loc, points, usb_ok)

    async def _reconcile(self, loc: StorageLocation, points: set[str], usb_ok: bool) -> None:
        rt = self._state(loc.id)
        item = self._detected.items.get(loc.uuid or "") if loc.kind == "usb" else None
        if loc.kind == "usb" and usb_ok:
            was_present = rt.present
            rt.present = item is not None
            if item is not None:
                rt.fstype = item.get("fstype") or rt.fstype
                rt.label = item.get("label")
                rt.size = item.get("size") or rt.size
                rt.supported = bool(item.get("supported"))
                rt.reason = item.get("reason")
            if not rt.present:
                rt.user_unmounted = False
            if was_present != rt.present and not rt.present and not rt.mounted:
                self._changed("unplugged", loc.id)
        is_mounted = str(self.mount_point(loc.id)) in points
        if rt.mounted and not is_mounted:
            rt.mounted, rt.root = False, None
            self._changed("unmounted", loc.id)
        elif is_mounted and not rt.mounted:
            if item and item.get("root"):
                root = Path(item["root"])  # the helper knows ext4 etc. keep data in <mp>/ncc
            elif item and item.get("mount_path"):
                root = Path(item["mount_path"])
            else:
                root = self.mount_point(loc.id)
            rt.mounted, rt.root = True, root
            self._gen[loc.id] = self._gen.get(loc.id, 0) + 1
            self._changed("mounted", loc.id)
        if loc.kind == "usb" and usb_ok and not rt.present and rt.mounted:
            try:
                await self._unmount(loc.id, lazy=True, user=False)
            except (MountFailed, LocationBusy) as exc:
                log.warning("unmount of unplugged %s failed: %s", loc.id, exc)
                rt.error = str(exc)[:500]
                return  # retried on the next poll; other locations continue
            self._changed("unplugged", loc.id)
            return
        if rt.mounted:
            await self._update_free(rt)
            if loc.kind == "smb" and rt.root is not None and not await self._healthy(rt.root):
                rt.error = "The share became unreachable"
                with contextlib.suppress(Exception):
                    await self._unmount(loc.id, lazy=True, user=False)
                rt.retry_at = time.monotonic() + rt.backoff
                self._changed("unreachable", loc.id)
            return
        want = loc.auto_mount and not rt.user_unmounted and time.monotonic() >= rt.retry_at
        if loc.kind == "usb":
            want = want and rt.present and rt.supported
        if want:
            try:
                await self._mount(loc.id, user=False)
            except Exception as exc:
                log.warning("auto-mount of %s failed: %s", loc.id, exc)
                rt.retry_at = time.monotonic() + rt.backoff
                rt.backoff = min(rt.backoff * 2, 60.0)

    async def _healthy(self, root: Path) -> bool:
        try:
            await self._probe((str(root), "health"), os.statvfs, root)
            return True
        except (OSError, TimeoutError, _ProbePending):  # a probe still pending is a hang
            return False
