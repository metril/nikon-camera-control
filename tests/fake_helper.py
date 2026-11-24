"""Fake ``ncc-storage`` helper: mounts are plain tmp dirs tracked in a fake mountinfo file."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class FakeHelper:
    def __init__(self, tmp: Path) -> None:
        self.base = tmp / "mnt"
        self.base.mkdir()
        self.mountinfo = tmp / "mountinfo"
        self.mountinfo.write_text("")
        self.usb: list[dict[str, Any]] = []
        self.mounted: set[str] = set()
        self.calls: list[list[str]] = []
        self.fail: dict[str, str] = {}  # verb or "verb:arg" -> stderr
        self.busy_unmount = False
        self.smb_up = True
        self.cred_seen: list[str] = []  # stdin (credentials) of each mount-smb call
        self.encrypted = True
        self.fstype: dict[str, str] = {}

    def plug(self, uuid: str, fstype: str = "exfat", supported: bool = True, **kw: Any) -> None:
        self.usb.append(
            {
                "name": f"sd{uuid[:2]}1",
                "uuid": uuid,
                "fstype": fstype,
                "label": kw.get("label"),
                "size": 1 << 30,
                "supported": supported,
                "reason": None if supported else "unsupported",
                "mounted": False,
                "mount_path": None,
                "root": None,
            }
        )

    def unplug(self, uuid: str) -> None:
        self.usb = [u for u in self.usb if u["uuid"] != uuid]

    def ismount(self, path: str) -> bool:
        return path in self.mounted

    def _sync(self) -> None:
        self.mountinfo.write_text(
            "".join(f"{i} 1 0:1 / {p} rw - tmpfs x rw\n" for i, p in enumerate(self.mounted))
        )

    def drop_mount(self, location_id: str) -> None:
        """Simulate the kernel dropping the mount behind the app's back."""
        self.mounted.discard(str(self.base / location_id))
        self._sync()

    async def runner(self, args: Sequence[str], stdin: str | None = None) -> tuple[int, str, str]:
        self.calls.append(list(args))
        verb = args[0]
        key = f"{verb}:{args[1]}" if len(args) > 1 else verb
        for k in (key, verb):
            if k in self.fail:
                return 1, "", self.fail[k]
        if verb == "list-usb":
            return 0, json.dumps(self.usb), ""
        if verb == "mount-usb":
            item = next((u for u in self.usb if u["uuid"] == args[1]), None)
            if item is None:
                return 1, "", "no such device"
            lid = f"usb-{args[1]}"
            mp = self.base / lid
            mp.mkdir(exist_ok=True)
            self.mounted.add(str(mp))
            self._sync()
            return 0, json.dumps({"id": lid, "root": str(mp), "fstype": item["fstype"]}), ""
        if verb == "mount-smb":
            self.cred_seen.append(stdin or "")
            if not self.smb_up:
                return 1, "", "mount error(113): No route to host"
            lid = f"smb-{args[1]}"
            mp = self.base / lid
            mp.mkdir(exist_ok=True)
            self.mounted.add(str(mp))
            self._sync()
            return (
                0,
                json.dumps(
                    {"id": lid, "root": str(mp), "fstype": "cifs", "encrypted": self.encrypted}
                ),
                "",
            )
        if verb == "unmount":
            if self.busy_unmount:
                return 16, "", "busy"
            self.mounted.discard(str(self.base / args[1]))
            self._sync()
            return 0, "", ""
        if verb == "fsck":
            return 0, "clean", ""
        return 2, "", "bad verb"
