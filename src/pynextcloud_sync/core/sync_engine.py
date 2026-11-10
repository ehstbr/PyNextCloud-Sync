from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from gi.repository import Gio, GLib

from pynextcloud_sync.nextcloud.command import BoundedOutputCapture, CommandSpec


@dataclass(frozen=True)
class SyncResult:
    exit_code: int
    duration: float
    output: str
    classification: str

    @property
    def successful(self) -> bool:
        return self.exit_code == 0


class SyncEngine:
    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self.process: Gio.Subprocess | None = None

    @property
    def running(self) -> bool:
        return self.process is not None

    def run(self, spec: CommandSpec, callback: Callable[[SyncResult], None]) -> None:
        if self.process is not None:
            raise RuntimeError("A synchronization process is already running.")
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        launcher = Gio.SubprocessLauncher.new(flags)
        for key, value in spec.environment.items():
            launcher.setenv(key, value, True)
        started = time.monotonic()
        safe_argv = [arg for arg in spec.argv]
        self.logger.info("Starting nextcloudcmd: %s", " ".join(safe_argv))
        try:
            process = launcher.spawnv(spec.argv)
        except GLib.Error as exc:
            result = SyncResult(127, 0.0, str(exc), "sync_error")
            callback(result)
            return

        self.process = process
        worker = threading.Thread(
            target=self._collect, args=(process, started, callback),
            name="pynextcloud-sync-output", daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            process.force_exit()
            process.wait(None)
            self.process = None
            callback(SyncResult(1, time.monotonic() - started, str(exc), "sync_error"))

    def _collect(
        self, process: Gio.Subprocess, started: float,
        callback: Callable[[SyncResult], None],
    ) -> None:
        stream = process.get_stdout_pipe()
        capture = BoundedOutputCapture(max_lines=200)
        pending = b""

        def record(raw: bytes) -> None:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            safe = self.logger.redactor.redact(line)
            capture.feed(safe)
            self.logger.info("CMD %s", safe)

        try:
            while chunk := stream.read_bytes(64 * 1024, None).get_data():
                *lines, pending = (pending + chunk).split(b"\n")
                for line in lines:
                    record(line)
            if pending:
                record(pending)
        except GLib.Error as exc:
            self.logger.warning("Could not read nextcloudcmd output: %s", exc)
        finally:
            try:
                stream.close(None)
            except GLib.Error as exc:
                self.logger.warning("Could not close nextcloudcmd output: %s", exc)

        exit_code = 1
        try:
            process.wait(None)
            if process.get_if_exited():
                exit_code = process.get_exit_status()
        except GLib.Error as exc:
            self.logger.warning("nextcloudcmd wait failed: %s", exc)
        result = SyncResult(
            exit_code, time.monotonic() - started,
            capture.output, capture.classification(exit_code),
        )
        GLib.idle_add(self._completed, callback, result)

    def _completed(
        self, callback: Callable[[SyncResult], None], result: SyncResult,
    ) -> bool:
        self.process = None
        callback(result)
        return GLib.SOURCE_REMOVE

    def cancel(self) -> None:
        if self.process is None:
            return
        try:
            self.process.send_signal(15)
        except GLib.Error:
            self.process.force_exit()
