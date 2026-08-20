from __future__ import annotations

import ctypes
import errno
import os
import struct
from pathlib import Path
from typing import Any, Callable

from gi.repository import GLib

from .exclusions import ExclusionMatcher


IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000

WATCH_MASK = (
    IN_ATTRIB
    | IN_CLOSE_WRITE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)
EVENT_STRUCT = struct.Struct("iIII")


class InotifyLimitError(RuntimeError):
    pass


class InotifyOverflowError(RuntimeError):
    pass


class InotifyWatcher:
    def __init__(
        self,
        root: Path,
        matcher: ExclusionMatcher,
        on_change: Callable[[Path], None],
        on_degraded: Callable[[Exception], None],
        logger: Any,
    ) -> None:
        self.root = root
        self.matcher = matcher
        self.on_change = on_change
        self.on_degraded = on_degraded
        self.logger = logger
        self.fd = -1
        self.source_id = 0
        # One entry is retained per directory. Strings are notably lighter than
        # pathlib objects in large trees and are converted only when an event arrives.
        self.watches: dict[int, str] = {}
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_init1.restype = ctypes.c_int
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_add_watch.restype = ctypes.c_int
        self._libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self._libc.inotify_rm_watch.restype = ctypes.c_int

    @property
    def watch_count(self) -> int:
        return len(self.watches)

    def start(self) -> None:
        if self.fd >= 0:
            return
        flags = os.O_NONBLOCK | os.O_CLOEXEC
        self.fd = self._libc.inotify_init1(flags)
        if self.fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._add_tree(self.root)
            self.source_id = GLib.io_add_watch(
                self.fd, GLib.IOCondition.IN | GLib.IOCondition.HUP, self._on_io
            )
            self.logger.info("inotify active with %s watched directories.", self.watch_count)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        self.watches.clear()

    def _add_tree(self, directory: Path) -> None:
        for current, directories, _files in os.walk(directory):
            self._add_watch(Path(current))
            directories[:] = [
                name
                for name in directories
                if not os.path.islink(os.path.join(current, name))
            ]

    def _add_watch(self, directory: Path) -> None:
        encoded = os.fsencode(directory)
        descriptor = self._libc.inotify_add_watch(self.fd, encoded, WATCH_MASK)
        if descriptor < 0:
            error = ctypes.get_errno()
            if error == errno.ENOSPC:
                exc = InotifyLimitError("The system inotify watch limit was reached.")
                self.on_degraded(exc)
                raise exc
            if error in {errno.ENOENT, errno.EACCES}:
                self.logger.warning("Could not watch directory %s: %s", directory, os.strerror(error))
                return
            raise OSError(error, os.strerror(error), directory)
        self.watches[descriptor] = os.fspath(directory)

    def _on_io(self, _fd: int, condition: GLib.IOCondition) -> bool:
        if condition & GLib.IOCondition.HUP:
            self.on_degraded(RuntimeError("The inotify file descriptor was closed."))
            return GLib.SOURCE_REMOVE
        try:
            while True:
                chunk = os.read(self.fd, 64 * 1024)
                if not chunk:
                    break
                self._parse(chunk)
        except BlockingIOError:
            pass
        except InotifyOverflowError as exc:
            self.on_degraded(exc)
            return GLib.SOURCE_REMOVE
        except OSError as exc:
            self.on_degraded(exc)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _parse(self, data: bytes) -> None:
        offset = 0
        while offset + EVENT_STRUCT.size <= len(data):
            wd, mask, _cookie, name_length = EVENT_STRUCT.unpack_from(data, offset)
            offset += EVENT_STRUCT.size
            raw_name = data[offset : offset + name_length]
            offset += name_length
            name = os.fsdecode(raw_name.split(b"\0", 1)[0]) if name_length else ""
            if mask & IN_Q_OVERFLOW:
                raise InotifyOverflowError(
                    "The inotify event queue overflowed; local event history is incomplete."
                )
            directory = self.watches.get(wd)
            if directory is None:
                continue
            path = Path(directory, name) if name else Path(directory)
            is_directory = bool(mask & IN_ISDIR)
            if mask & IN_IGNORED:
                self.watches.pop(wd, None)
                continue
            if is_directory and mask & (IN_CREATE | IN_MOVED_TO):
                try:
                    self._add_tree(path)
                except (OSError, InotifyLimitError) as exc:
                    self.logger.warning("Could not extend inotify watches: %s", exc)
            if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                self.watches.pop(wd, None)
            if not is_directory and self.matcher.matches_name(name):
                self.logger.debug("Ignored disposable file event: %s", name)
                continue
            self.logger.debug("Local change detected: %s", path)
            self.on_change(path)
