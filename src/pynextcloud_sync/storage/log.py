from __future__ import annotations

import datetime as dt
import logging
import os
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pynextcloud_sync.util.paths import ensure_private_directory, state_dir
from pynextcloud_sync.util.redact import Redactor


class CallbackHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.callback(self.format(record))
        except Exception:
            self.handleError(record)


class DailyFileHandler(logging.Handler):
    """Write to one private, predictably named file per local calendar day."""

    def __init__(
        self,
        directory: Path,
        prefix: str,
        retention_days: int,
        date_provider: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        super().__init__()
        self.directory = ensure_private_directory(directory)
        self.prefix = prefix
        self.retention_days = retention_days
        self.date_provider = date_provider
        self._active_date: dt.date | None = None
        self._stream: Any = None
        self.prune()

    @property
    def active_path(self) -> Path:
        stamp = self._active_date or self.date_provider()
        return self.directory / f"{self.prefix}-{stamp.isoformat()}.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            current_date = self.date_provider()
            if self._stream is None or current_date != self._active_date:
                self._open_for_date(current_date)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _open_for_date(self, value: dt.date) -> None:
        if self._stream:
            self._stream.close()
        self._active_date = value
        path = self.active_path
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._stream = os.fdopen(descriptor, "a", encoding="utf-8")
        self.prune()

    def prune(self) -> None:
        files = sorted(
            self.directory.glob(f"{self.prefix}-????-??-??.log"),
            key=lambda path: path.name,
            reverse=True,
        )
        for expired in files[max(1, self.retention_days) :]:
            try:
                expired.unlink()
            except OSError:
                pass

    def close(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None
        super().close()


class AppLogger:
    LIVE_HISTORY_LINES = 500

    def __init__(
        self,
        path: Path | None = None,
        *,
        save_to_disk: bool = True,
        retention_days: int = 30,
        date_provider: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.directory = ensure_private_directory(path.parent if path else state_dir())
        self.prefix = path.stem if path else "pynextcloud-sync"
        self.retention_days = retention_days
        self.save_to_disk = False
        self._date_provider = date_provider
        self.redactor = Redactor()
        self._listeners: list[Callable[[str], None]] = []
        self._live_history: deque[str] = deque(maxlen=self.LIVE_HISTORY_LINES)
        self._file_handler: DailyFileHandler | None = None
        self.logger = logging.getLogger(f"pynextcloud_sync.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        callback_handler = CallbackHandler(self._emit_live)
        callback_handler.setFormatter(self.formatter)
        self.logger.addHandler(callback_handler)
        self._callback_handler = callback_handler
        self.configure(save_to_disk=save_to_disk, retention_days=retention_days)

    @property
    def path(self) -> Path:
        stamp = self._date_provider().isoformat()
        return self.directory / f"{self.prefix}-{stamp}.log"

    def configure(self, *, save_to_disk: bool, retention_days: int) -> None:
        retention_days = max(1, min(365, int(retention_days)))
        unchanged = (
            self.save_to_disk == bool(save_to_disk)
            and self.retention_days == retention_days
            and (not save_to_disk or self._file_handler is not None)
        )
        if unchanged:
            return
        if self._file_handler:
            self.logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None
        self.save_to_disk = bool(save_to_disk)
        self.retention_days = retention_days
        if self.save_to_disk:
            handler = DailyFileHandler(
                self.directory,
                self.prefix,
                self.retention_days,
                self._date_provider,
            )
            handler.setFormatter(self.formatter)
            self.logger.addHandler(handler)
            self._file_handler = handler

    def add_secret(self, secret: str | None) -> None:
        self.redactor.add_secret(secret)

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def _emit_live(self, line: str) -> None:
        safe_line = self.redactor.redact(line)
        self._live_history.append(safe_line)
        for listener in tuple(self._listeners):
            listener(safe_line)

    def recent_lines(self, lines: int = 5) -> list[str]:
        if lines <= 0:
            return []
        return list(self._live_history)[-lines:]

    def _safe_argument(self, value: object) -> object:
        # Numeric values must stay numeric so logging placeholders such as %.1f work.
        if isinstance(value, (int, float, complex)) or value is None:
            return value
        return self.redactor.redact(value)

    def _log(self, level: int, message: object, *args: object) -> None:
        safe_message = self.redactor.redact(message)
        safe_args = tuple(self._safe_argument(arg) for arg in args)
        self.logger.log(level, safe_message, *safe_args)

    def debug(self, message: object, *args: object) -> None:
        self._log(logging.DEBUG, message, *args)

    def info(self, message: object, *args: object) -> None:
        self._log(logging.INFO, message, *args)

    def warning(self, message: object, *args: object) -> None:
        self._log(logging.WARNING, message, *args)

    def error(self, message: object, *args: object) -> None:
        self._log(logging.ERROR, message, *args)

    def _log_paths(self) -> list[Path]:
        return sorted(self.directory.glob(f"{self.prefix}-????-??-??.log"))

    @staticmethod
    def _tail_path(path: Path, lines: int, block_size: int = 8192) -> list[str]:
        if lines <= 0:
            return []
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            chunks: list[bytes] = []
            newline_count = 0
            while position > 0 and newline_count <= lines:
                size = min(block_size, position)
                position -= size
                handle.seek(position)
                chunk = handle.read(size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
        data = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
        return data.splitlines()[-lines:]

    def tail(self, lines: int = 300) -> str:
        if lines <= 0:
            return ""
        if not self.save_to_disk:
            return "\n".join(self.recent_lines(lines))
        content: list[str] = []
        remaining = lines
        try:
            for path in reversed(self._log_paths()):
                selected = self._tail_path(path, remaining)
                content[:0] = selected
                remaining -= len(selected)
                if remaining <= 0:
                    break
            return "\n".join(content[-lines:])
        except OSError:
            return "\n".join(self.recent_lines(lines))

    def close(self) -> None:
        if self._file_handler:
            self.logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None
        self.logger.removeHandler(self._callback_handler)
        self._callback_handler.close()
        self._listeners.clear()
        self._live_history.clear()
