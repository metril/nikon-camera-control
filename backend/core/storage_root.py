"""Where services write: the (dynamic) storage target, as a small protocol.

Services take a ``StorageRoot`` instead of a fixed output directory. ``LocationService``
implements it for the real app; ``FixedRoot`` wraps a plain directory (tests, tools).
``root()`` raises ``NoTargetError`` when no target is mounted, so a write can never fall
through to the container filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

CACHE_DIRNAME = ".ncc"
FAT32_MAX_FILE = 4 * 1024**3 - 1


class StorageRoot(Protocol):
    def root(self) -> Path:
        """Mounted target directory (raises NoTargetError)."""
        ...

    def cache(self) -> Path:
        """Rebuildable cache dir on the target: ``<root>/.ncc`` (raises NoTargetError)."""
        ...

    def stored(self, path: Path) -> None:
        """A file was finalized: hash it, record SHA256SUMS, schedule a backup (blocking)."""
        ...

    def check_file_size(self, size: int | None) -> None:
        """Raise FileTooLarge when ``size`` cannot be stored on the target filesystem."""
        ...


class FixedRoot:
    """A plain directory as storage root (no hashing, no limits)."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def root(self) -> Path:
        return self._root

    def cache(self) -> Path:
        return self._root / CACHE_DIRNAME

    def stored(self, path: Path) -> None:
        return None

    def check_file_size(self, size: int | None) -> None:
        return None


def as_root(value: Path | StorageRoot) -> StorageRoot:
    return FixedRoot(value) if isinstance(value, Path) else value
