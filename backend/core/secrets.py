"""Write-only secret storage (``<data>/secrets.json``, mode 0600): SMB passwords.

Same atomic-write pattern as ``ApiKeyStore``. Secrets are never returned by the API.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class SecretStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.error("secrets file %s unreadable; treating as empty", self._path)
            return {}
        raw = data.get("smb") if isinstance(data, dict) else None
        return {k: v for k, v in raw.items() if isinstance(v, str)} if isinstance(raw, dict) else {}

    def _save(self, smb: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".secrets-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"smb": smb}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def get_smb(self, location_id: str) -> str | None:
        with self._lock:
            return self._load().get(location_id)

    def set_smb(self, location_id: str, password: str | None) -> None:
        """Store (or with None/'' remove) the password of a location."""
        with self._lock:
            smb = self._load()
            if password:
                smb[location_id] = password
            else:
                smb.pop(location_id, None)
            self._save(smb)

    def has_smb(self, location_id: str) -> bool:
        return self.get_smb(location_id) is not None
