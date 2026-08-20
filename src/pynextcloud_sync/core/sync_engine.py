from __future__ import annotations

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
        self._cancellable: Gio.Cancellable | None = None

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
        self._cancellable = Gio.Cancellable()
        stream = Gio.DataInputStream.new(process.get_stdout_pipe())
        capture = BoundedOutputCapture(max_lines=200)
        status = {"stream_done": False, "process_done": False}

        def maybe_finish() -> None:
            if not status["stream_done"] or not status["process_done"]:
                return
            exit_code = process.get_exit_status() if process.get_if_exited() else 1
            output = capture.output
            duration = time.monotonic() - started
            classification = capture.classification(exit_code)
            self.process = None
            self._cancellable = None
            callback(SyncResult(exit_code, duration, output, classification))

        def read_next() -> None:
            stream.read_line_async(GLib.PRIORITY_DEFAULT, self._cancellable, line_ready, None)

        def line_ready(source: Gio.DataInputStream, result: Gio.AsyncResult, _data: object = None) -> None:
            try:
                line, _length = source.read_line_finish_utf8(result)
            except GLib.Error as exc:
                self.logger.warning("Could not read nextcloudcmd output: %s", exc)
                line = None
            if line is None:
                status["stream_done"] = True
                maybe_finish()
                return
            safe = self.logger.redactor.redact(line)
            capture.feed(safe)
            self.logger.info("CMD %s", safe)
            read_next()

        def process_ready(source: Gio.Subprocess, result: Gio.AsyncResult, _data: object = None) -> None:
            try:
                source.wait_finish(result)
            except GLib.Error as exc:
                self.logger.warning("nextcloudcmd wait failed: %s", exc)
            status["process_done"] = True
            maybe_finish()

        read_next()
        process.wait_async(self._cancellable, process_ready, None)

    def cancel(self) -> None:
        if self.process is None:
            return
        try:
            self.process.send_signal(15)
        except GLib.Error:
            self.process.force_exit()
