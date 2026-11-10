from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pynextcloud_sync.core.safety import InventorySnapshot, is_sync_database_name
from pynextcloud_sync.util.i18n import _
from pynextcloud_sync.util.paths import ensure_private_directory


class CheckpointError(RuntimeError):
    pass


def directory_identity(path: Path) -> list[int]:
    details = path.stat()
    if not stat.S_ISDIR(details.st_mode):
        raise NotADirectoryError(path)
    return [details.st_dev, details.st_ino]


def snapshot_seal(
    snapshot: InventorySnapshot,
    check: Callable[[], None],
) -> str:
    """Identify a stopped engine's inventory and journal without opening SQLite."""
    digest = hashlib.sha256()

    def add(entry: tuple) -> None:
        digest.update(json.dumps(entry, separators=(",", ":")).encode("ascii"))
        digest.update(b"\n")

    for path, entry in sorted(snapshot.entries.items()):
        check()
        details = (snapshot.root / path).lstat()
        if details.st_mtime_ns != entry.modified_ns or (
            entry.kind == "file" and details.st_size != entry.size
        ):
            raise CheckpointError(_("The protected copy changed while it was being checked."))
        add((
            path, entry.kind, entry.size, details.st_mtime_ns,
            details.st_ctime_ns, details.st_mode, details.st_ino,
        ))
    for path in sorted(snapshot.root.iterdir()):
        if is_sync_database_name(path.name):
            details = path.lstat()
            if not stat.S_ISREG(details.st_mode):
                raise CheckpointError(_("The protected copy has an invalid synchronization journal."))
            add((
                path.name, details.st_size, details.st_mtime_ns,
                details.st_ctime_ns, details.st_ino,
            ))
    return digest.hexdigest()


class BootstrapCheckpoint:
    """One protected operation, with a lease that also survives in the child."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "session.json"

    @contextmanager
    def lease(self) -> Iterator[int]:
        ensure_private_directory(self.root)
        fd = os.open(self.root / "session.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CheckpointError(
                    _("Another protected synchronization is still running. Try again after it exits.")
                ) from exc
            yield fd
        finally:
            # An inherited file description holds the lease until the child
            # exits, even if the application process is interrupted.
            os.close(fd)

    def load(self) -> dict | None:
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.loads(handle.read(8192))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeError) as exc:
            raise CheckpointError(_("The saved protected operation could not be read.")) from exc
        if (
            not isinstance(data, dict)
            or data.get("format") != 1
            or data.get("phase") not in ("download", "ready", "apply")
            or not isinstance(data.get("stage"), str)
            or not re.fullmatch(r"protected-[a-z0-9_]+", data["stage"])
        ):
            raise CheckpointError(_("The saved protected operation is invalid."))
        return data

    def stage(self, data: dict) -> Path:
        path = self.root / data["stage"]
        try:
            details = path.lstat()
        except OSError as exc:
            raise CheckpointError(_("The saved protected copy is missing.")) from exc
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or details.st_mode & 0o077
            or [details.st_dev, details.st_ino] != data.get("stage_identity")
        ):
            raise CheckpointError(_("The saved protected folder no longer matches this operation."))
        return path

    def save(self, data: dict) -> None:
        fd, name = tempfile.mkstemp(dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self._sync_directory()

    def _sync_directory(self) -> None:
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
