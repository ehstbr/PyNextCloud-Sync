from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


_LOG_MESSAGE = re.compile(
    r"^(?:[\d :.-]+\s+)?\[\s*(?:info|debug|warning)\s+(?P<category>(?:nextcloud\.)?sync\.[\w.]+|default)"
    r"(?:\s+[^\]]*)?\s*\](?:\s*\[[^\]]+\])?:\s*(?P<message>.*)$"
)
_QUOTED_PATH = r'(?P<path>"(?:[^"\\]|\\.)*")'
_COMPLETED_JOB = re.compile(
    r"Completed propagation of\s+" + _QUOTED_PATH
    + r"\s+by\s+(?:OCC::)?(?P<job>\w+)\([^)]*\)"
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
    "PropagateLocalRemove": "remove",
    "PropagateRemoteDelete": "remove",
    "PropagateLocalRename": "rename",
    "PropagateRemoteMove": "rename",
    "PropagateLocalMkdir": "mkdir",
    "PropagateRemoteMkdir": "mkdir",
}


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


class ActivityCapture:
    """Capture confirmed nextcloudcmd jobs in one subprocess, including its retries."""

    def __init__(self, redact: Callable[[str], str] = str) -> None:
        self._redact = redact
        self._events: dict[tuple[str, str], ActivityEvent] = {}
        self._lock = Lock()
        self._propagation_reported = False
        self._finalized = False
        self._incomplete = False

    def feed(self, line: str, at: float | None = None) -> None:
        if "Completed propagation of" in line or "Could not complete propagation of" in line:
            self._record_job(line, at)
        elif "Item completed" in line and "sync.propagator.bulkupload" in line:
            self._record_job(line, at, bulk=True)
        elif "Sync run took" in line or "Post-Reconcile end" in line:
            match = _LOG_MESSAGE.search(line)
            if match and match["category"].endswith("sync.engine"):
                message = match["message"]
                if message.startswith("#### Post-Reconcile end "):
                    self._propagation_reported = True
                elif message.startswith("Sync run took "):
                    self._finalized = self._propagation_reported
                    self._propagation_reported = False
        elif "PropagateRootDirectory::" in line and "emit finished" in line:
            match = _LOG_MESSAGE.search(line)
            if match and match["category"].removeprefix("nextcloud.") in _ROOT_JOB_CATEGORIES:
                self._propagation_reported = match["message"].endswith("SyncFileItem::Success")
        elif "Another sync is needed, but not done" in line:
            match = _LOG_MESSAGE.search(line)
            if match and match["category"] == "default" and match["message"].startswith("Another sync is needed, but not done"):
                self._incomplete = True

    def _record_job(self, line: str, at: float | None, *, bulk: bool = False) -> None:
        logged = _LOG_MESSAGE.search(line)
        category = "sync.propagator.bulkupload" if bulk else "sync.propagator"
        if not logged or not logged["category"].endswith(category):
            return
        pattern = _COMPLETED_BULK_ITEM if bulk else _COMPLETED_JOB
        match = pattern.match(logged["message"])
        if not match or match["status"] != "Success":
            self._incomplete = True
            return
        job = "" if bulk else match["job"]
        if job == "PropagateIgnoreJob":
            return
        if bulk or job.startswith("PropagateUploadFile"):
            kind = "upload"
        elif job.startswith("PropagateDownloadFile"):
            kind = "download"
        else:
            kind = _OTHER_JOBS.get(job)
        path = _quoted_path(match["path"])
        if not kind or not path:
            self._incomplete = True
            return
        key = (kind, path)
        with self._lock:
            if key not in self._events:
                self._events[key] = ActivityEvent(
                    kind, time.time() if at is None else at, self._redact(path)
                )

    def report(self, *, fully_read: bool = True, successful: bool = True) -> ActivityReport:
        with self._lock:
            events = tuple(self._events.values())
        return ActivityReport(
            events, fully_read and successful and self._finalized and not self._incomplete
        )
