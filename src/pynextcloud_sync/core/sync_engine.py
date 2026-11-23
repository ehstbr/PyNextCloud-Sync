from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from gi.repository import Gio, GLib

from pynextcloud_sync.nextcloud.activity import ActivityCapture, ActivityReport, SyncProgress
from pynextcloud_sync.nextcloud.command import BoundedOutputCapture, CommandSpec


@dataclass(frozen=True)
class SyncResult:
    exit_code: int
    duration: float
    output: str
    classification: str
    activity: ActivityReport = ActivityReport()
    interrupted: bool = False

    @property
    def successful(self) -> bool:
        return self.exit_code == 0 and not self.interrupted


class SyncEngine:
    OUTPUT_DRAIN_SECONDS = 2
    CANCEL_GRACE_SECONDS = 10

    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self.process: Gio.Subprocess | None = None
        self._activity: ActivityCapture | None = None
        self._output_cancel: Gio.Cancellable | None = None
        self._output_drain_source = 0
        self._cancel_source = 0
        self._cancel_requested = False

    @property
    def running(self) -> bool:
        return self.process is not None

    @property
    def progress(self) -> SyncProgress | None:
        return self._activity.progress() if self._activity else None

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
        self._activity = ActivityCapture(self.logger.redactor.redact)
        self._cancel_requested = False
        self._output_cancel = Gio.Cancellable()
        process.wait_async(None, self._process_exited)
        worker = threading.Thread(
            target=self._collect, args=(process, started, callback, self._activity),
            name="pynextcloud-sync-output", daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            process.force_exit()
            process.wait(None)
            self.process = None
            self._activity = None
            callback(SyncResult(1, time.monotonic() - started, str(exc), "sync_error"))

    def _collect(
        self, process: Gio.Subprocess, started: float,
        callback: Callable[[SyncResult], None],
        activity: ActivityCapture | None = None,
    ) -> None:
        stream = process.get_stdout_pipe()
        capture = BoundedOutputCapture(max_lines=200)
        activity = activity or ActivityCapture(self.logger.redactor.redact)
        pending = b""
        fully_read = True
        output_cancel = self._output_cancel

        def record(raw: bytes) -> None:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            safe = self.logger.redactor.redact(line)
            capture.feed(safe)
            activity.feed(line)
            self.logger.info("CMD %s", safe)

        try:
            while chunk := stream.read_bytes(64 * 1024, output_cancel).get_data():
                *lines, pending = (pending + chunk).split(b"\n")
                for line in lines:
                    record(line)
            if pending:
                record(pending)
        except GLib.Error as exc:
            fully_read = False
            self.logger.warning("Could not read nextcloudcmd output: %s", exc)
        except Exception as exc:
            fully_read = False
            self.logger.error("Could not process nextcloudcmd output: %s", exc)
            GLib.idle_add(self._cancel_failed_reader, process)
        finally:
            try:
                stream.close(None)
            except GLib.Error as exc:
                self.logger.warning("Could not close nextcloudcmd output: %s", exc)

        exit_code = 1
        interrupted = self._cancel_requested
        try:
            process.wait(None)
            if process.get_if_exited():
                exit_code = process.get_exit_status()
            else:
                interrupted = True
        except GLib.Error as exc:
            self.logger.warning("nextcloudcmd wait failed: %s", exc)
        interrupted = interrupted or self._cancel_requested
        result = SyncResult(
            exit_code, time.monotonic() - started,
            capture.output, capture.classification(exit_code),
            activity.report(fully_read=fully_read, successful=exit_code == 0), interrupted,
        )
        GLib.idle_add(self._completed, process, callback, result)

    def _process_exited(self, process: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            process.wait_finish(result)
        except GLib.Error as exc:
            self.logger.warning("Could not observe nextcloudcmd completion: %s", exc)
            return
        if self.process is process:
            self._output_drain_source = GLib.timeout_add_seconds(
                self.OUTPUT_DRAIN_SECONDS, self._stop_output_reader, process,
            )

    def _stop_output_reader(self, process: Gio.Subprocess) -> bool:
        self._output_drain_source = 0
        if self.process is process and self._output_cancel:
            self.logger.warning("nextcloudcmd exited, but its output pipe remained open; closing the reader.")
            self._output_cancel.cancel()
        return GLib.SOURCE_REMOVE

    def _cancel_failed_reader(self, process: Gio.Subprocess) -> bool:
        if self.process is process:
            self.cancel()
        return GLib.SOURCE_REMOVE

    def _completed(
        self, process: Gio.Subprocess, callback: Callable[[SyncResult], None], result: SyncResult,
    ) -> bool:
        if self.process is not process:
            return GLib.SOURCE_REMOVE
        for attribute in ("_output_drain_source", "_cancel_source"):
            source = getattr(self, attribute)
            if source:
                GLib.source_remove(source)
                setattr(self, attribute, 0)
        self.process = None
        self._activity = None
        self._output_cancel = None
        callback(result)
        return GLib.SOURCE_REMOVE

    def interrupted_activity(self) -> ActivityReport:
        if self._activity:
            return self._activity.report(fully_read=False)
        return ActivityReport()

    def cancel(self) -> None:
        if self.process is None or self._cancel_requested:
            return
        self._cancel_requested = True
        process = self.process
        try:
            process.send_signal(15)
        except GLib.Error:
            process.force_exit()
        self._cancel_source = GLib.timeout_add_seconds(
            self.CANCEL_GRACE_SECONDS, self._force_cancel, process,
        )

    def _force_cancel(self, process: Gio.Subprocess) -> bool:
        self._cancel_source = 0
        if self.process is process and process.get_identifier() is not None:
            self.logger.warning("nextcloudcmd did not stop after SIGTERM; terminating the cancelled process.")
            process.force_exit()
        return GLib.SOURCE_REMOVE
