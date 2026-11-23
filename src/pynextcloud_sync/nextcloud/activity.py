from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from threading import Lock


_LOG_MESSAGE = re.compile(
    r"^(?:[\d :.-]+\s+)?\[\s*(?:info|debug|warning)\s+(?P<category>(?:nextcloud\.)?sync\.[\w.]+|default)"
    r"(?:\s+[^\]]*)?\s*\](?:\s*\[[^\]]+\])?:\s*(?P<message>.*)$"
)
_QUOTED_PATH = r'(?P<path>"(?:[^"\\]|\\.)*")'
_JOB_TARGET = _QUOTED_PATH + r"\s+by\s+(?:OCC::)?(?P<job>\w+)\([^)]*\)"
_STARTED_JOB = re.compile(
    r"Starting (?:\S+ )?propagation of\s+" + _JOB_TARGET
)
_COMPLETED_JOB = re.compile(
    r"(?P<result>Completed|Could not complete) propagation of\s+" + _JOB_TARGET
    + r"\s+with status\s+(?:OCC::)?SyncFileItem::(?P<status>\w+)"
)
_COMPLETED_BULK_ITEM = re.compile(
    r"Item completed\s+" + _QUOTED_PATH
    + r"\s+(?:OCC::)?SyncFileItem::(?P<status>\w+)"
    + r"\s+(?:CSyncEnums::)?CSYNC_INSTRUCTION_(?:NEW|SYNC|TYPE_CHANGE)\b"
)
_QT_ESCAPE = re.compile(r"\\(?:U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2}|.)")
_ROOT_JOB_CATEGORIES = {"sync.propagator", "sync.propagator.root.directory"}
_OTHER_JOBS = {
    "PropagateLocalRemove": "remove_local",
    "PropagateRemoteDelete": "remove_remote",
    "PropagateLocalRename": "rename",
    "PropagateRemoteMove": "rename",
    "PropagateLocalMkdir": "mkdir",
    "PropagateRemoteMkdir": "mkdir",
}


class SyncPhase(IntEnum):
    CHECKING = 0
    APPLYING = 1
    FINALIZING = 2


@dataclass(frozen=True, slots=True)
class SyncProgress:
    phase: SyncPhase = SyncPhase.CHECKING
    completed: int = 0
    active: int = 0


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    kind: str
    at: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ActivityReport:
    events: tuple[ActivityEvent, ...] = ()
    complete: bool = False


def _quoted_path(value: str) -> str:
    def convert_escape(match: re.Match[str]) -> str:
        escape = match[0][1:]
        if len(escape) > 1 and escape[0] in {"x", "U"}:
            return json.dumps(chr(int(escape[1:], 16)))[1:-1]
        return {"a": r"\u0007", "v": r"\u000b", "0": r"\u0000"}.get(escape, match[0])

    try:
        path = json.loads(_QT_ESCAPE.sub(convert_escape, value))
        path.encode("utf-8")
    except (ValueError, UnicodeError):
        return ""
    if not path or path.startswith("/") or "\x00" in path or ".." in path.split("/"):
        return ""
    return path


def _operation_kind(job: str) -> str | None:
    if job == "BulkPropagatorJob" or job.startswith("PropagateUploadFile"):
        return "upload"
    if job.startswith("PropagateDownloadFile"):
        return "download"
    return _OTHER_JOBS.get(job)


class ActivityCapture:
    """Capture confirmed nextcloudcmd jobs in one subprocess, including its retries."""

    def __init__(self, redact: Callable[[str], str] = str) -> None:
        self._redact = redact
        self._events: dict[tuple[str, str], ActivityEvent] = {}
        self._active_jobs: set[tuple[str, str]] = set()
        self._phase = SyncPhase.CHECKING
        self._lock = Lock()
        self._propagation_reported = False
        self._finalized = False
        self._incomplete = False

    def feed(self, line: str, at: float | None = None) -> None:
        if not (
            " propagation of " in line or "Item completed" in line
            or "Sync run took" in line or "Reconcile" in line
            or "emit finished" in line or "another sync is needed" in line
            or "Another sync is needed" in line
        ):
            return
        logged = _LOG_MESSAGE.search(line)
        if not logged:
            return
        category = logged["category"].removeprefix("nextcloud.")
        message = logged["message"]
        if category == "sync.propagator" and message.startswith("Starting "):
            self._record_start(message)
        elif category == "sync.propagator" and message.startswith(
            ("Completed propagation of ", "Could not complete propagation of ")
        ):
            self._record_job(message, at)
        elif category == "sync.propagator.bulkupload" and message.startswith("Item completed "):
            self._record_job(message, at, bulk=True)
        elif category == "sync.engine":
            self._record_phase(message)
        elif category in _ROOT_JOB_CATEGORIES and message.startswith("PropagateRootDirectory::") and "emit finished" in message:
            with self._lock:
                self._propagation_reported = message.endswith("SyncFileItem::Success")
                self._phase = SyncPhase.FINALIZING
                self._active_jobs.clear()
        elif category == "default":
            with self._lock:
                if message.startswith("Restarting Sync, because another sync is needed"):
                    self._phase = SyncPhase.CHECKING
                    self._active_jobs.clear()
                elif message.startswith("Another sync is needed, but not done"):
                    self._incomplete = True

    def _record_phase(self, message: str) -> None:
        with self._lock:
            if message.startswith("#### Post-Reconcile end "):
                self._propagation_reported = True
                self._phase = max(self._phase, SyncPhase.APPLYING)
            elif message.startswith("#### Reconcile (aboutToPropagate OK) "):
                self._phase = SyncPhase.APPLYING
            elif message.startswith("Sync run took "):
                self._finalized = self._propagation_reported
                self._propagation_reported = False
                self._phase = SyncPhase.FINALIZING
                self._active_jobs.clear()

    def _record_start(self, message: str) -> None:
        match = _STARTED_JOB.match(message)
        if not match:
            return
        kind = _operation_kind(match["job"])
        path = _quoted_path(match["path"])
        if kind and path:
            key = (kind, path)
            with self._lock:
                self._phase = SyncPhase.APPLYING
                if key not in self._events:
                    self._active_jobs.add(key)

    def _record_job(self, message: str, at: float | None, *, bulk: bool = False) -> None:
        pattern = _COMPLETED_BULK_ITEM if bulk else _COMPLETED_JOB
        match = pattern.match(message)
        if not match:
            with self._lock:
                self._incomplete = True
            return
        job = "BulkPropagatorJob" if bulk else match["job"]
        kind = _operation_kind(job)
        path = _quoted_path(match["path"])
        with self._lock:
            if job == "PropagateIgnoreJob" and match["status"] == "Success":
                return
            if not kind or not path:
                self._incomplete = True
                return
            self._phase = SyncPhase.APPLYING
            key = (kind, path)
            self._active_jobs.discard(key)
            if match["status"] != "Success" or (not bulk and match["result"] != "Completed"):
                self._incomplete = True
                return
            if key not in self._events:
                self._events[key] = ActivityEvent(
                    "remove" if kind.startswith("remove_") else kind,
                    time.time() if at is None else at,
                    self._redact(path),
                )

    def progress(self) -> SyncProgress:
        with self._lock:
            return SyncProgress(self._phase, len(self._events), len(self._active_jobs))

    def report(self, *, fully_read: bool = True, successful: bool = True) -> ActivityReport:
        with self._lock:
            return ActivityReport(
                tuple(self._events.values()),
                fully_read and successful and self._finalized and not self._incomplete,
            )
