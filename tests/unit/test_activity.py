from __future__ import annotations

import datetime as dt
import queue
import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.nextcloud.activity import (
    ActivityCapture, ActivityEvent, ActivityReport, SyncPhase, SyncProgress,
)
from pynextcloud_sync.storage.history import SyncAttempt, SyncHistory
from pynextcloud_sync.storage.log import AppLogger


def cmd(category: str, message: str) -> str:
    return f"11-17 01:00:01:024 [ info nextcloud.sync.{category} ]: {message}"


ROOT_DONE = cmd(
    "propagator", "PropagateRootDirectory::slotDirDeletionJobsFinished emit finished OCC::SyncFileItem::Success"
)
RUN_DONE = cmd("engine", "Sync run took  24 ms")
POST_RECONCILE = cmd("engine", "#### Post-Reconcile end ###################  2 ms")


def downloaded(path: str) -> str:
    return cmd(
        "propagator",
        f'Completed propagation of "{path}" by OCC::PropagateDownloadFile(0x1234) with status OCC::SyncFileItem::Success',
    )


class ActivityTests(unittest.TestCase):
    def test_live_progress_combines_transfers_and_deletions(self) -> None:
        activity = ActivityCapture()
        self.assertEqual(activity.progress(), SyncProgress())
        jobs = (
            ("download.txt", "PropagateDownloadFile", "NEW"),
            ("upload.txt", "PropagateUploadFileNG", "SYNC"),
            ("local.txt", "PropagateLocalRemove", "REMOVE"),
            ("remote.txt", "PropagateRemoteDelete", "REMOVE"),
        )
        for path, job, instruction in jobs:
            activity.feed(cmd(
                "propagator",
                f'Starting CSyncEnums::CSYNC_INSTRUCTION_{instruction} propagation of "{path}" by OCC::{job}(0x1234)',
            ))
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, 0, 4))

        for completed, (path, job, _) in enumerate(jobs, 1):
            confirmation = cmd(
                "propagator",
                f'Completed propagation of "{path}" by OCC::{job}(0x1234) with status OCC::SyncFileItem::Success',
            )
            activity.feed(confirmation)
            activity.feed(confirmation)
            self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, completed, 4 - completed))

        activity.feed(POST_RECONCILE)
        activity.feed(RUN_DONE)
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.FINALIZING, 4, 0))

    def test_live_progress_uses_bulk_confirmations_and_clears_failed_attempts(self) -> None:
        activity = ActivityCapture()
        started = cmd(
            "propagator",
            'Starting CSyncEnums::CSYNC_INSTRUCTION_NEW propagation of "upload.txt" by OCC::PropagateUploadFileNG(0x1)',
        )
        activity.feed(started)
        activity.feed(started)
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, 0, 1))
        activity.feed(cmd(
            "propagator",
            'Could not complete propagation of "upload.txt" by OCC::PropagateUploadFileNG(0x1) with status OCC::SyncFileItem::SoftError',
        ))
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, 0, 0))
        activity.feed(cmd(
            "propagator",
            'Completed propagation of "upload.txt" by OCC::BulkPropagatorJob(0x2) with status OCC::SyncFileItem::Success',
        ))
        activity.feed(cmd(
            "propagator.bulkupload",
            'Item completed "upload.txt" OCC::SyncFileItem::Success CSyncEnums::CSYNC_INSTRUCTION_NEW ""',
        ))
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, 1, 0))

        activity.feed('[ debug default ]: Restarting Sync, because another sync is needed 1')
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.CHECKING, 1, 0))
        activity.feed(started)
        self.assertEqual(activity.progress(), SyncProgress(SyncPhase.APPLYING, 1, 0))

    def test_uses_confirmations_not_attempts_and_preserves_literal_paths(self) -> None:
        activity = ActivityCapture()
        for line in (
            cmd("propagator", 'Starting propagation of "unconfirmed.txt" by OCC::PropagateDownloadFile(0x1234)'),
            cmd("networkjob", 'GET "unconfirmed.txt"'),
            downloaded(r'Comercial/Relat\u00F3rio & \"vendas\".xlsx'),
            downloaded(r'Comercial/Relat\u00F3rio & \"vendas\".xlsx'),
            downloaded(r'Estoque/Relat\u00F3rio & \"vendas\".xlsx'),
            cmd(
                "propagator.bulkupload",
                'Item completed "upload.xlsx" OCC::SyncFileItem::Success CSyncEnums::CSYNC_INSTRUCTION_NEW ""',
            ),
            ROOT_DONE,
            RUN_DONE,
        ):
            activity.feed(line, 100.0)

        report = activity.report()
        self.assertTrue(report.complete)
        self.assertEqual(
            report.events,
            (
                ActivityEvent("download", 100.0, 'Comercial/Relatório & "vendas".xlsx'),
                ActivityEvent("download", 100.0, 'Estoque/Relatório & "vendas".xlsx'),
                ActivityEvent("upload", 100.0, "upload.xlsx"),
            ),
        )
        self.assertFalse(activity.report(fully_read=False).complete)

    def test_requires_evidence_for_a_run_without_file_changes(self) -> None:
        activity = ActivityCapture()
        activity.feed(RUN_DONE)
        self.assertFalse(activity.report().complete)
        activity.feed(ROOT_DONE)
        activity.feed(RUN_DONE)
        self.assertEqual(activity.report(), ActivityReport((), True))

    def test_modern_nextcloudcmd_can_finish_without_a_root_completion_line(self) -> None:
        activity = ActivityCapture()
        activity.feed(POST_RECONCILE)
        self.assertFalse(activity.report().complete)
        activity.feed(RUN_DONE)
        self.assertFalse(activity.report(successful=False).complete)
        self.assertEqual(activity.report(), ActivityReport((), True))

    def test_root_failure_in_modern_category_does_not_confirm_an_empty_run(self) -> None:
        activity = ActivityCapture()
        activity.feed(POST_RECONCILE)
        activity.feed(cmd(
            "propagator.root.directory",
            "PropagateRootDirectory::slotSubJobsFinished emit finished OCC::SyncFileItem::FatalError",
        ))
        activity.feed(RUN_DONE)
        self.assertFalse(activity.report().complete)

    def test_reported_file_error_does_not_confirm_an_empty_run(self) -> None:
        activity = ActivityCapture()
        activity.feed(POST_RECONCILE)
        activity.feed(cmd(
            "propagator",
            'Could not complete propagation of "example.txt" by OCC::PropagateDownloadFile(0x1234) with status OCC::SyncFileItem::SoftError',
        ))
        activity.feed(RUN_DONE)
        self.assertFalse(activity.report().complete)

    def test_folder_changes_are_distinct_from_file_transfers(self) -> None:
        activity = ActivityCapture()
        for job, kind in (
            ("PropagateRemoteMkdir", "mkdir"), ("PropagateRemoteMove", "rename"),
            ("PropagateLocalRemove", "remove"), ("PropagateUploadFileNG", "upload"),
        ):
            activity.feed(cmd(
                "propagator",
                f'Completed propagation of "{kind}" by OCC::{job}(0x1234) with status OCC::SyncFileItem::Success',
            ), 100.0)
        self.assertEqual([event.kind for event in activity.report().events], ["mkdir", "rename", "remove", "upload"])


class HistoryTests(unittest.TestCase):
    ACCOUNT = {
        "server_url": "https://cloud.example.com",
        "local_root": "/tmp/nextcloud",
        "login_name": "alice",
    }

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.logger = AppLogger(Path(self.tempdir.name) / "test.log")
        self.addCleanup(self.logger.close)

    def history(self, account=None, *, last_sync=None, bootstrap_at=None) -> SyncHistory:
        history = SyncHistory(
            self.logger, account or self.ACCOUNT, last_sync, lambda callback: callback(),
            bootstrap_at=bootstrap_at,
        )
        self.addCleanup(history.close)
        return history

    def recent(self, history: SyncHistory):
        result = queue.Queue()
        history.recent(10, result.put)
        return result.get(timeout=5)

    def details(self, history: SyncHistory, run_id: str):
        result = queue.Queue()
        history.details(run_id, 10, result.put)
        return result.get(timeout=5)

    def test_baseline_event_updates_its_run_after_a_later_run_exists(self) -> None:
        history = self.history()
        first = SyncAttempt.start()
        second = SyncAttempt.start()
        first_download = ActivityEvent("download", first.started_at, "docs/prices.xlsx")
        history.record(first, "completed", ActivityReport((first_download,), True))
        history.record(second, "completed", ActivityReport((), True))
        entries = self.recent(history)
        self.assertEqual([entry.id for entry in entries], [second.id, first.id])
        self.assertEqual(entries[1].downloads, 1)
        self.assertEqual(entries[0].downloads, 0)

        event = ActivityEvent("baseline", second.started_at + 1)
        history.add_event(first.id, event)
        self.assertEqual(self.details(history, first.id), [event, first_download])
        self.assertEqual(self.details(history, second.id), [])
        history.close()
        reopened = self.history()
        self.assertEqual([entry.event_count for entry in self.recent(reopened)], [0, 2])
        self.assertEqual(self.recent(self.history(self.ACCOUNT | {"login_name": "other"})), [])

    def test_history_stays_in_memory_when_disk_logging_is_disabled(self) -> None:
        self.logger.configure(save_to_disk=False, retention_days=30)
        history = self.history()
        run = SyncAttempt.start()
        history.record(run, "blocked", reason="Safety check")
        self.assertEqual(self.recent(history)[0].reason, "Safety check")
        self.assertFalse((self.logger.directory / "sync-history.sqlite3").exists())
        new_session = self.history()
        self.assertEqual(self.recent(new_session), [])

    def test_summaries_count_saved_file_changes_by_type(self) -> None:
        history = self.history()
        attempt = SyncAttempt.start()
        changes = (
            ActivityEvent("remove", attempt.started_at, "obsolete.txt"),
            ActivityEvent("remove", attempt.started_at, "obsolete_folder"),
            ActivityEvent("rename", attempt.started_at, "new_name.txt"),
            ActivityEvent("mkdir", attempt.started_at, "new_folder"),
        )
        history.record(attempt, "completed", ActivityReport(changes, True))
        (entry,) = self.recent(history)
        self.assertEqual((entry.removals, entry.renames, entry.folders_created), (2, 1, 1))
        self.assertEqual(entry.other_changes, 4)

        history.close()
        reopened = self.history()
        (stored,) = self.recent(reopened)
        self.assertEqual(stored, entry)

        self.logger.configure(save_to_disk=False, retention_days=30)
        session = self.history()
        session.record(attempt, "completed", ActivityReport(changes[:1], True))
        (stored_in_memory,) = self.recent(session)
        self.assertEqual(stored_in_memory.removals, 1)

    def test_imports_only_the_legacy_run_corroborated_by_the_active_account(self) -> None:
        last_sync = dt.datetime.now(dt.timezone.utc).isoformat()
        earlier = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
        self.logger.info("Starting nextcloudcmd: nextcloudcmd /tmp/nextcloud https://cloud.example.com")
        self.logger.info("CMD %s", downloaded("example.txt"))
        self.logger.info("CMD %s", ROOT_DONE)
        self.logger.info("CMD %s", RUN_DONE)
        self.logger.info("Synchronization completed successfully.")
        self.logger.info("Safety baseline updated with %s local files.", 1)
        other = self.history(
            self.ACCOUNT | {"login_name": "other"},
            last_sync=last_sync, bootstrap_at=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat(),
        )
        self.assertEqual(self.recent(other), [])

        history = self.history(last_sync=last_sync, bootstrap_at=earlier)
        (entry,) = self.recent(history)
        self.assertEqual((entry.downloads, entry.event_count), (1, 2))
        self.assertEqual([event.kind for event in self.details(history, entry.id)], ["baseline", "download"])
        self.assertEqual(self.recent(self.history(last_sync=last_sync, bootstrap_at=earlier)), [entry])


if __name__ == "__main__":
    unittest.main()
