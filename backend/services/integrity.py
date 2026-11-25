"""SHA-256 integrity files: per-directory ``SHA256SUMS`` (``sha256sum -c`` format) plus an
optional ``<file>.sha256`` sidecar. They live on the location itself, so they travel with
any copy and can be checked anywhere with ``sha256sum -c``."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

SUMS_NAME = "SHA256SUMS"
SIDECAR_EXT = ".sha256"
PARTIAL_EXT = ".ncc-partial"
CACHE_DIRNAME = ".ncc"
CHUNK = 1024 * 1024
_LINE = re.compile(r"^(\\)?([0-9a-fA-F]{64}) [ *](.+)$")
_UNESCAPE = re.compile(r"\\(.)")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _dir_lock(directory: Path) -> threading.Lock:
    key = str(directory)
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def is_aux(name: str) -> bool:
    """Names that are bookkeeping, not data: sums, sidecars, partials, hidden, ``.part``."""
    return (
        name == SUMS_NAME
        or name.startswith(".")
        or name.endswith((SIDECAR_EXT, PARTIAL_EXT, ".part", ".tmp"))
        or ".part." in name
    )


def sha256_file(path: Path, cancel: threading.Event | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
    return h.hexdigest()


def format_line(name: str, digest: str) -> str:
    """One ``sha256sum`` line (GNU escaping: names with ``\\`` or newline get a ``\\`` prefix)."""
    if "\\" in name or "\n" in name:
        esc = name.replace("\\", "\\\\").replace("\n", "\\n")
        return f"\\{digest}  {esc}\n"
    return f"{digest}  {name}\n"


def _unescape(esc: str) -> str:
    return _UNESCAPE.sub(lambda m: "\n" if m.group(1) == "n" else m.group(1), esc)


def read_sums(directory: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = (directory / SUMS_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.split("\n"):
        m = _LINE.match(line)
        if m:
            name = _unescape(m.group(3)) if m.group(1) else m.group(3)
            out[name] = m.group(2).lower()
    return out


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sums-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def update_sums(
    directory: Path, add: dict[str, str] | None = None, remove: set[str] | None = None
) -> None:
    """Atomically add/replace/remove entries of ``directory/SHA256SUMS``. An emptied file
    is deleted."""
    with _dir_lock(directory):
        sums = read_sums(directory)
        sums.update(add or {})
        for n in remove or ():
            sums.pop(n, None)
        target = directory / SUMS_NAME
        if not sums:
            with contextlib.suppress(OSError):
                target.unlink()
            return
        _write_atomic(target, "".join(format_line(n, h) for n, h in sorted(sums.items())))


def record(path: Path, *, sidecar: bool = True, digest: str | None = None) -> str:
    """Hash ``path`` (unless ``digest`` is given) and record it in SHA256SUMS (+ sidecar)."""
    digest = digest or sha256_file(path)
    update_sums(path.parent, {path.name: digest})
    side = path.with_name(path.name + SIDECAR_EXT)
    if sidecar:
        _write_atomic(side, format_line(path.name, digest))
    else:
        with contextlib.suppress(OSError):
            side.unlink()
    return digest


def forget(path: Path) -> None:
    """Drop ``path`` from SHA256SUMS and delete its sidecar."""
    update_sums(path.parent, remove={path.name})
    with contextlib.suppress(OSError):
        path.with_name(path.name + SIDECAR_EXT).unlink()


def iter_files(root: Path, sub: str = "") -> Iterator[Path]:
    """Data files under ``root/sub`` (bookkeeping and the ``.ncc`` cache excluded)."""
    stack = [root / sub if sub else root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name != CACHE_DIRNAME and not e.name.startswith("."):
                        stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=False) and not is_aux(e.name):
                    yield Path(e.path)
            except OSError:
                continue


@dataclass
class VerifyReport:
    checked: int = 0
    ok: int = 0
    mismatched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # listed in SHA256SUMS but gone
    unlisted: list[str] = field(default_factory=list)  # on disk, not listed
    cancelled: bool = False


_MEDIA_EXT = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".nef", ".nrw", ".cr2", ".cr3", ".arw", ".dng"}
    | {".raf", ".orf", ".rw2", ".mov", ".mp4", ".avi", ".mkv", ".m4v"}
)


def verify(
    root: Path,
    sub: str = "",
    *,
    cancel: threading.Event | None = None,
    progress: Callable[[int], None] | None = None,
) -> VerifyReport:
    """Re-hash files under ``root/sub`` against each directory's own SHA256SUMS."""
    rep = VerifyReport()
    base = root / sub if sub else root
    dirs: dict[Path, list[Path]] = {}
    for f in iter_files(root, sub):
        dirs.setdefault(f.parent, []).append(f)
    # directories that only have a SHA256SUMS (all files deleted) still report "missing"
    for walk_dir, _dn, fn in os.walk(base):
        dp = Path(walk_dir)
        if CACHE_DIRNAME in dp.relative_to(root).parts:
            continue
        if SUMS_NAME in fn:
            dirs.setdefault(dp, [])
    for d in sorted(dirs):
        sums = read_sums(d)
        present = {f.name for f in dirs[d]}
        for name, want in sorted(sums.items()):
            if "/" in name or name.startswith(".") or os.path.isabs(name):
                continue  # a checksum file only describes its own directory
            rel = (d / name).relative_to(root).as_posix()
            if name not in present and not (d / name).is_file():
                rep.missing.append(rel)
                continue
            if cancel is not None and cancel.is_set():
                rep.cancelled = True
                return rep
            try:
                got = sha256_file(d / name, cancel)
            except InterruptedError:
                rep.cancelled = True
                return rep
            except OSError:
                rep.missing.append(rel)
                continue
            rep.checked += 1
            if got == want:
                rep.ok += 1
            else:
                rep.mismatched.append(rel)
            if progress is not None:
                progress(rep.checked)
        for f in dirs[d]:
            if f.name not in sums and f.suffix.lower() in _MEDIA_EXT:
                rep.unlisted.append(f.relative_to(root).as_posix())
    return rep
