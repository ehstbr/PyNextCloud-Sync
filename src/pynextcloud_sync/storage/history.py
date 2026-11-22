from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import time
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any

from pynextcloud_sync.core.safety import account_fingerprint
from pynextcloud_sync.nextcloud.activity import ActivityCapture, ActivityEvent, ActivityReport


@dataclass(frozen=True, slots=True)
class SyncAttempt:
    id: str
    started_at: float

    @classmethod
    def start(cls) -> SyncAttempt:
        return cls(uuid.uuid4().hex, time.time())


@dataclass(frozen=True, slots=True)
class SyncSummary:
    id: str
    started_at: float
    ended_at: float
    outcome: str
    reason: str
    exit_code: int | None
    complete: bool
    downloads: int
    uploads: int
    other_changes: int
    event_count: int
    removals: int = 0
    renames: int = 0
    folders_created: int = 0


_LEGACY_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (?:INFO|WARNING|ERROR)\s+(.*)$"
)
_SUMMARY_COLUMNS = (
    "id, started_at, ended_at, outcome, reason, exit_code, complete, "
    "downloads, uploads, other_changes, event_count"
)


def _summary(
    attempt: SyncAttempt, ended_at: float, outcome: str, reason: str,
    exit_code: int | None, report: ActivityReport,
) -> SyncSummary:
    counts = Counter(event.kind for event in report.events)
    downloads = counts["download"]
    uploads = counts["upload"]
    return SyncSummary(
        attempt.id, attempt.started_at, ended_at, outcome, reason, exit_code,
        report.complete, downloads, uploads,
        counts["remove"] + counts["rename"] + counts["mkdir"], len(report.events),
        removals=counts["remove"], renames=counts["rename"], folders_created=counts["mkdir"],
    )


def _legacy_run(
    log: str, last_sync: float, command_suffix: str, redact: Callable[[str], str],
) -> tuple[SyncSummary, tuple[ActivityEvent, ...]] | None:
    """Recover the run corroborated by the account's saved last-success timestamp."""
    attempt = None
    capture = None
    ended_at = None
    baseline = ()
    for line in log.splitlines():
        match = _LEGACY_LINE.match(line)
        if not match:
            continue
        stamp, message = match.groups()
        if message.startswith("Starting nextcloudcmd: "):
            if ended_at is not None:
                break
            attempt = capture = None
            if message.endswith(command_suffix):
                started_at = dt.datetime.fromisoformat(stamp).timestamp()
                attempt = SyncAttempt(f"legacy-{last_sync:.6f}", started_at)
                capture = ActivityCapture(redact)
        elif capture and ended_at is None and message.startswith("CMD "):
            capture.feed(message[4:], dt.datetime.fromisoformat(stamp).timestamp())
        elif capture and message == "Synchronization completed successfully.":
            candidate = dt.datetime.fromisoformat(stamp).timestamp()
            if 0 <= candidate - int(last_sync) <= 1:
                ended_at = candidate
            else:
                attempt = capture = None
        elif ended_at is not None and message.startswith("Synchronization triggers: "):
            break
        elif ended_at is not None and message.startswith("Safety baseline updated with "):
            baseline = (ActivityEvent("baseline", dt.datetime.fromisoformat(stamp).timestamp()),)
            break
    if attempt is None or capture is None or ended_at is None:
        return None
    report = capture.report()
    report = ActivityReport(report.events + baseline, report.complete)
    return _summary(attempt, ended_at, "completed", "", 0, report), report.events


class SyncHistory:
    """Serialize history I/O and dispatch snapshots back to the GTK main loop."""

    SESSION_LIMIT = 20

    def __init__(
        self, logger: Any, account: dict, last_sync: str | None,
        dispatch: Callable[..., Any],
        *, bootstrap_at: str | None = None,
    ) -> None:
        self._logger = logger
        self._path = logger.directory / "sync-history.sqlite3"
        self._account = account_fingerprint(account)
        self._legacy_suffix = f" {account['local_root']} {account['server_url']}"
        self._legacy_timestamp = last_sync
        self._bootstrap_at = bootstrap_at
        self._legacy_checked = False
        self._dispatch = dispatch
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pynextcloud-history")
        self._settings = (logger.save_to_disk, logger.retention_days)
        self._session: dict[str, tuple[SyncSummary, tuple[ActivityEvent, ...]]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._warned = False
        self._closed = False
        self._submission_lock = Lock()

    def configure(self, enabled: bool, retention_days: int) -> None:
        settings = (enabled, retention_days)
        if settings != self._settings:
            self._settings = settings
            self._changed()

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def record(
        self, attempt: SyncAttempt, outcome: str, report: ActivityReport = ActivityReport(),
        *, reason: str = "", exit_code: int | None = None, ended_at: float | None = None,
    ) -> None:
        self._submit(
            self._record, attempt, outcome, report, reason, exit_code,
            time.time() if ended_at is None else ended_at,
        )

    def add_event(self, run_id: str, event: ActivityEvent) -> None:
        self._submit(self._add_event, run_id, event)

    def recent(self, limit: int, receive: Callable[[list[SyncSummary]], None]) -> None:
        self._submit(lambda: self._deliver(receive, self._recent(limit)))

    def details(
        self, run_id: str, limit: int, receive: Callable[[list[ActivityEvent]], None],
        *, offset: int = 0,
    ) -> None:
        self._submit(lambda: self._deliver(receive, self._details(run_id, limit, offset)))

    def _submit(self, work: Callable[..., None], *args: object) -> None:
        with self._submission_lock:
            if not self._closed:
                self._executor.submit(work, *args)

    def _deliver(self, callback: Callable, *args: object) -> None:
        def deliver() -> bool:
            if not self._closed:
                callback(*args)
            return False

        self._dispatch(deliver)

    def _changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def close(self) -> None:
        with self._submission_lock:
            self._closed = True
            self._executor.shutdown(wait=False)
        self._listeners.clear()

    def _warn(self, error: Exception) -> None:
        if not self._warned:
            self._warned = True
            self._logger.warning("Could not access synchronization history: %s", error)

    @contextmanager
    def _database(self):
        os.close(os.open(self._path, os.O_CREAT | os.O_WRONLY, 0o600))
        with closing(sqlite3.connect(self._path)) as database, database:
            database.execute("PRAGMA foreign_keys = ON")
            database.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL,
                    started_at REAL NOT NULL, ended_at REAL NOT NULL,
                    outcome TEXT NOT NULL, reason TEXT NOT NULL, exit_code INTEGER,
                    complete INTEGER NOT NULL, downloads INTEGER NOT NULL,
                    uploads INTEGER NOT NULL, other_changes INTEGER NOT NULL,
                    event_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_by_account_and_date ON runs (account, ended_at DESC);
                CREATE INDEX IF NOT EXISTS runs_by_date ON runs (ended_at);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, at REAL NOT NULL, detail TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_run ON events (run_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS file_changes_by_run ON events (run_id, kind)
                    WHERE kind IN ('remove', 'rename', 'mkdir');
            """)
            if not self._legacy_checked:
                self._import_legacy(database)
                self._legacy_checked = True
            retention = dt.date.today() - dt.timedelta(days=self._settings[1] - 1)
            cutoff = dt.datetime.combine(retention, dt.time()).timestamp()
            database.execute("DELETE FROM runs WHERE ended_at < ?", (cutoff,))
            yield database

    def _import_legacy(self, database: sqlite3.Connection) -> None:
        if not self._legacy_timestamp or not self._bootstrap_at or database.execute(
            "SELECT 1 FROM runs WHERE account = ? LIMIT 1", (self._account,)
        ).fetchone():
            return
        try:
            stamp = dt.datetime.fromisoformat(self._legacy_timestamp).timestamp()
            if stamp < dt.datetime.fromisoformat(self._bootstrap_at).timestamp():
                return
            recovered = _legacy_run(
                self._logger.tail(5_000), stamp,
                self._logger.redactor.redact(self._legacy_suffix), self._logger.redactor.redact,
            )
        except (TypeError, ValueError, OverflowError, OSError):
            return
        if recovered:
            self._insert(database, *recovered)

    def _insert(
        self, database: sqlite3.Connection, entry: SyncSummary,
        events: tuple[ActivityEvent, ...],
    ) -> None:
        database.execute(
            f"INSERT INTO runs (account, {_SUMMARY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._account, entry.id, entry.started_at, entry.ended_at, entry.outcome,
                entry.reason, entry.exit_code, entry.complete, entry.downloads, entry.uploads,
                entry.other_changes, entry.event_count,
            ),
        )
        database.executemany(
            "INSERT INTO events (run_id, kind, at, detail) VALUES (?, ?, ?, ?)",
            ((entry.id, event.kind, event.at, event.detail) for event in events),
        )

    def _record(
        self, attempt: SyncAttempt, outcome: str, report: ActivityReport,
        reason: str, exit_code: int | None, ended_at: float,
    ) -> None:
        entry = _summary(
            attempt, ended_at, outcome, self._logger.redactor.redact(reason), exit_code, report
        )
        saved = False
        if self._settings[0]:
            try:
                with self._database() as database:
                    self._insert(database, entry, report.events)
                saved = True
            except (sqlite3.Error, OSError) as error:
                self._warn(error)
        if not saved:
            self._session[entry.id] = (entry, report.events)
            if len(self._session) > self.SESSION_LIMIT:
                self._session.pop(next(iter(self._session)))
        self._deliver(self._changed)

    def _add_event(self, run_id: str, event: ActivityEvent) -> None:
        if run_id in self._session:
            entry, events = self._session[run_id]
            self._session[run_id] = (
                replace(entry, event_count=entry.event_count + 1), (*events, event),
            )
        elif self._settings[0]:
            try:
                with self._database() as database:
                    updated = database.execute(
                        "UPDATE runs SET event_count = event_count + 1 WHERE account = ? AND id = ?",
                        (self._account, run_id),
                    )
                    if updated.rowcount:
                        database.execute(
                            "INSERT INTO events (run_id, kind, at, detail) VALUES (?, ?, ?, ?)",
                            (run_id, event.kind, event.at, event.detail),
                        )
            except (sqlite3.Error, OSError) as error:
                self._warn(error)
        self._deliver(self._changed)

    def _recent(self, limit: int) -> list[SyncSummary]:
        entries = [entry for entry, _events in self._session.values()]
        if self._settings[0]:
            try:
                with self._database() as database:
                    rows = database.execute(
                        f"""
                        SELECT {_SUMMARY_COLUMNS},
                            COUNT(CASE WHEN kind = 'remove' THEN 1 END),
                            COUNT(CASE WHEN kind = 'rename' THEN 1 END),
                            COUNT(CASE WHEN kind = 'mkdir' THEN 1 END)
                        FROM (
                            SELECT {_SUMMARY_COLUMNS} FROM runs WHERE account = ?
                            ORDER BY ended_at DESC, id DESC LIMIT ?
                        ) AS recent
                        LEFT JOIN events ON events.run_id = recent.id
                            AND kind IN ('remove', 'rename', 'mkdir')
                        GROUP BY recent.id
                        """,
                        (self._account, limit),
                    )
                    entries.extend(SyncSummary(*row) for row in rows)
            except (sqlite3.Error, OSError) as error:
                self._warn(error)
        return sorted(entries, key=lambda item: (item.ended_at, item.id), reverse=True)[:limit]

    def _details(self, run_id: str, limit: int, offset: int) -> list[ActivityEvent]:
        if run_id in self._session:
            events = self._session[run_id][1]
            end = max(len(events) - offset, 0)
            return list(reversed(events[max(0, end - limit):end]))
        if self._settings[0]:
            try:
                with self._database() as database:
                    rows = database.execute(
                        "SELECT kind, at, detail FROM events JOIN runs ON runs.id = events.run_id "
                        "WHERE account = ? AND run_id = ? ORDER BY sequence DESC LIMIT ? OFFSET ?",
                        (self._account, run_id, limit, offset),
                    )
                    return [ActivityEvent(*row) for row in rows]
            except (sqlite3.Error, OSError) as error:
                self._warn(error)
        return []
