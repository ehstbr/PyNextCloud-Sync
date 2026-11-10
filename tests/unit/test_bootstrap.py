from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pynextcloud_sync.core.bootstrap import (
    BootstrapAnalysis,
    BootstrapPaused,
    BootstrapPolicy,
    BootstrapRunner,
    analyze_inventories,
    inventory_differences,
)
from pynextcloud_sync.core.bootstrap_checkpoint import CheckpointError
from pynextcloud_sync.core.bootstrap_progress import BootstrapProgressReporter, measure_download
from pynextcloud_sync.storage.config import ConfigStore
from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.safety import find_sync_databases, scan_inventory


class FakeLogger:
    redactor = types.SimpleNamespace(redact=lambda value: value)

    def info(self, *_args: object) -> None:
        pass

    def warning(self, *_args: object) -> None:
        pass


class BootstrapTests(unittest.TestCase):
    def _config(self, root: Path) -> object:
        return types.SimpleNamespace(
            data={
                "account": {
                    "server_url": "https://cloud.example.com",
                    "login_name": "alice",
                    "local_root": str(root),
                },
                "sync": {
                    "exclude_patterns": [],
                    "exclude_patterns_enabled": True,
                    "max_sync_retries": 3,
                    "detailed_output": True,
                },
                "network": {},
            }
        )

    def test_analysis_classifies_both_sides_and_hashes_ambiguous_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local"
            remote = Path(directory) / "remote"
            local.mkdir()
            remote.mkdir()
            (local / "local.txt").write_text("local", encoding="utf-8")
            (remote / "remote.txt").write_text("remote", encoding="utf-8")
            (local / "same.txt").write_text("same", encoding="utf-8")
            (remote / "same.txt").write_text("same", encoding="utf-8")
            (local / "conflict.txt").write_text("first", encoding="utf-8")
            (remote / "conflict.txt").write_text("other", encoding="utf-8")
            os.utime(local / "same.txt", ns=(1_000_000_000, 1_000_000_000))
            os.utime(remote / "same.txt", ns=(8_000_000_000, 8_000_000_000))

            result = analyze_inventories(
                scan_inventory(local, ExclusionMatcher([])),
                scan_inventory(remote, ExclusionMatcher([])),
            )

            local_only, remote_only, identical, conflicts, unsupported = result
            self.assertEqual(local_only, ("local.txt",))
            self.assertEqual(remote_only, ("remote.txt",))
            self.assertIn("same.txt", identical)
            self.assertEqual([item.path for item in conflicts], ["conflict.txt"])
            self.assertFalse(unsupported)

    def test_type_conflict_is_one_review_item_for_the_whole_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local"
            remote = Path(directory) / "remote"
            local.mkdir()
            remote.mkdir()
            (local / "shared").mkdir()
            (local / "shared" / "child.txt").write_text("child", encoding="utf-8")
            (remote / "shared").write_text("remote-file", encoding="utf-8")

            result = analyze_inventories(
                scan_inventory(local, ExclusionMatcher([])),
                scan_inventory(remote, ExclusionMatcher([])),
            )

            self.assertEqual([item.path for item in result[3]], ["shared"])
            self.assertNotIn("shared/child.txt", result[0])

    def test_nextcloud_priority_preserves_local_conflict_as_dated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local"
            stage = Path(directory) / "stage"
            local.mkdir()
            stage.mkdir()
            (local / "report.txt").write_text("computer", encoding="utf-8")
            (stage / "report.txt").write_text("nextcloud", encoding="utf-8")
            local_snapshot = scan_inventory(local, ExclusionMatcher([]))
            remote_snapshot = scan_inventory(stage, ExclusionMatcher([]))
            classified = analyze_inventories(local_snapshot, remote_snapshot)
            analysis = BootstrapAnalysis(
                local,
                stage,
                local_snapshot,
                remote_snapshot,
                classified[0],
                classified[1],
                classified[2],
                classified[3],
                (),
                classified[4],
                10**9,
            )

            BootstrapRunner(self._config(local), FakeLogger())._merge_into_staging(
                analysis, BootstrapPolicy.NEXTCLOUD_FIRST, {}
            )

            self.assertEqual((stage / "report.txt").read_text(), "nextcloud")
            copies = list(stage.glob("report (Computer copy *).txt"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_text(), "computer")

    def test_computer_priority_preserves_remote_directory_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "local"
            stage = Path(directory) / "stage"
            local.mkdir()
            stage.mkdir()
            (local / "shared").write_text("computer-file", encoding="utf-8")
            (stage / "shared").mkdir()
            (stage / "shared" / "remote.txt").write_text("remote", encoding="utf-8")
            local_snapshot = scan_inventory(local, ExclusionMatcher([]))
            remote_snapshot = scan_inventory(stage, ExclusionMatcher([]))
            classified = analyze_inventories(local_snapshot, remote_snapshot)
            analysis = BootstrapAnalysis(
                local,
                stage,
                local_snapshot,
                remote_snapshot,
                classified[0],
                classified[1],
                classified[2],
                classified[3],
                (),
                classified[4],
                10**9,
            )

            BootstrapRunner(self._config(local), FakeLogger())._merge_into_staging(
                analysis, BootstrapPolicy.COMPUTER_FIRST, {}
            )

            self.assertEqual((stage / "shared").read_text(), "computer-file")
            preserved = list(stage.glob("shared (Nextcloud copy *)"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual((preserved[0] / "remote.txt").read_text(), "remote")

    def test_sync_database_variants_are_detected_outside_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (".sync_abcd.db", ".sync_abcd.db-wal", "._sync_old.db"):
                (root / name).touch()
            (root / "normal.db").touch()

            databases = {path.name for path in find_sync_databases(root)}
            inventory = scan_inventory(root, ExclusionMatcher([]))

            self.assertEqual(
                databases,
                {".sync_abcd.db", ".sync_abcd.db-wal", "._sync_old.db"},
            )
            self.assertEqual(set(inventory.files), {"normal.db"})

    def test_final_verification_hashes_same_size_files_and_detects_extra_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected_root = Path(directory) / "expected"
            actual_root = Path(directory) / "actual"
            expected_root.mkdir()
            actual_root.mkdir()
            (expected_root / "same-size.txt").write_text("first", encoding="utf-8")
            (actual_root / "same-size.txt").write_text("other", encoding="utf-8")
            (actual_root / "unexpected.txt").write_text("extra", encoding="utf-8")

            differences = inventory_differences(
                scan_inventory(expected_root, ExclusionMatcher([])),
                scan_inventory(actual_root, ExclusionMatcher([])),
            )

            self.assertEqual(differences[0], ())
            self.assertEqual(differences[1], ("unexpected.txt",))
            self.assertEqual(differences[2], ("same-size.txt",))


class ProtectedOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        paths = patch.dict(os.environ, {
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        paths.start()
        self.addCleanup(paths.stop)
        self.config = ConfigStore(self.root / "settings.json")
        self.config.data["account"] = {
            "server_url": "https://cloud.example.com",
            "login_name": "alice",
            "local_root": str(self.root / "local"),
        }
        self.config.data["safety"]["bootstrap_mode"] = "setup"
        self.local = self.root / "local"
        self.local.mkdir()
        self.lines = []
        self.runner = BootstrapRunner(self.config, FakeLogger(), self.lines.append)

    @staticmethod
    def _finish_download(root: Path, _password: str, _lease: int) -> None:
        (root / "remote.txt").write_text("protected copy", encoding="utf-8")
        (root / ".sync_fixture.db").touch()

    def _wait(self, start):
        results = []
        finished = threading.Event()

        def callback(result, failure):
            results.append((result, failure))
            finished.set()

        start(callback)
        self.assertTrue(finished.wait(5), "worker did not finish")
        return results[0]

    def _analyze(self, runner=None, *, progress=lambda _state: None, restart=False, etag=None):
        runner = runner or self.runner
        return self._wait(
            lambda callback: runner.analyze(
                "fixture", progress, callback, restart=restart, remote_etag=etag
            )
        )

    def _execute(self, analysis, etag=None):
        return self._wait(lambda callback: self.runner.execute(
            analysis, "fixture", BootstrapPolicy.NEXTCLOUD_FIRST, {},
            lambda _state: None, callback, remote_etag=etag,
        ))

    def test_pause_during_download_stops_after_the_snapshot_and_reopens_without_download(self):
        def pause_during_download(progress):
            if progress.downloading:
                self.runner.pause()

        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download) as engine:
            analysis, error = self._analyze(progress=pause_during_download)
        self.assertIsNone(analysis)
        self.assertIsInstance(error, BootstrapPaused)
        self.assertEqual(engine.call_count, 1)
        saved = self.runner.checkpoint.load()
        self.assertEqual(saved["phase"], "ready")
        self.assertNotIn("fixture", self.runner.checkpoint.path.read_text())

        (self.local / "added.txt").write_text("added after pause", encoding="utf-8")
        reopened = BootstrapRunner(self.config, FakeLogger())
        with patch.object(reopened, "_run_sync") as engine:
            analysis, error = self._analyze(reopened)
        engine.assert_not_called()
        self.assertIsNone(error)
        self.assertTrue(analysis.resumed)
        self.assertEqual(analysis.remote_only, ("remote.txt",))
        self.assertEqual(analysis.local_only, ("added.txt",))
        self.assertEqual(analysis.staging_root.name, saved["stage"])

    def test_checkpoint_detects_same_size_edit_with_restored_timestamp(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            analysis, error = self._analyze()
        self.assertIsNone(error)
        path = analysis.staging_root / "remote.txt"
        before = path.stat()
        path.write_text("modified copy!", encoding="utf-8")
        self.assertEqual(before.st_size, path.stat().st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with patch.object(self.runner, "_run_sync") as engine:
            result, error = self._analyze()
        self.assertIsNone(result)
        self.assertIsInstance(error, CheckpointError)
        engine.assert_not_called()

    def test_resumed_copy_requires_an_unchanged_remote_folder_before_apply(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            _, error = self._analyze(etag='"original"')
        self.assertIsNone(error)
        with patch.object(self.runner, "_run_sync") as engine:
            _, error = self._analyze(etag='"changed"')
            self.assertIsInstance(error, CheckpointError)
            analysis, error = self._analyze(etag='"original"')
            self.assertIsNone(error)
            self.assertTrue(analysis.resumed)
            for etag in (None, '"changed"'):
                _, error = self._execute(analysis, etag=etag)
                self.assertIsInstance(error, CheckpointError)
            engine.assert_not_called()
            self.assertEqual(self.runner.checkpoint.load()["phase"], "ready")
            result, error = self._execute(analysis, etag='"original"')
        self.assertIsNone(error)
        self.assertEqual(result.synchronized_files, 1)

    def test_stage_link_is_rejected_without_touching_its_target(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            analysis, error = self._analyze()
        self.assertIsNone(error)
        actual = analysis.staging_root.rename(self.root / "moved-stage")
        analysis.staging_root.symlink_to(actual, target_is_directory=True)
        with patch.object(self.runner, "_run_sync") as engine:
            _, error = self._analyze()
        self.assertIsInstance(error, CheckpointError)
        engine.assert_not_called()
        self.assertTrue((actual / "remote.txt").is_file())

    def test_changed_exclusions_cannot_reuse_the_copy(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            _, error = self._analyze()
        self.assertIsNone(error)
        self.config.data["sync"]["exclude_patterns"].append("remote.txt")
        with patch.object(self.runner, "_run_sync") as engine:
            analysis, error = self._analyze()
        self.assertIsNone(analysis)
        self.assertIsInstance(error, CheckpointError)
        engine.assert_not_called()

    def test_interrupted_download_always_restarts_in_an_empty_folder(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            old, error = self._analyze()
        self.assertIsNone(error)
        with self.runner.checkpoint.lease():
            saved = self.runner.checkpoint.load()
            saved["phase"] = "download"
            self.runner.checkpoint.save(saved)

        def download(root, password, lease):
            self.assertNotEqual(root, old.staging_root)
            self.assertFalse(list(root.iterdir()))
            self._finish_download(root, password, lease)

        with patch.object(self.runner, "_run_sync", side_effect=download) as engine:
            new, error = self._analyze()
        self.assertIsNone(error)
        self.assertFalse(new.resumed)
        self.assertEqual(engine.call_count, 1)
        self.assertFalse(old.staging_root.exists())

    def test_interrupted_application_requires_fresh_review_and_preserves_its_copy(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            analysis, error = self._analyze()
        self.assertIsNone(error)
        with patch.object(self.runner, "_run_sync", side_effect=RuntimeError("interrupted")):
            result, error = self._execute(analysis)
        self.assertIsNone(result)
        self.assertEqual(str(error), "interrupted")
        self.assertFalse(self.config.data["safety"]["bootstrap_complete"])
        self.assertEqual(self.runner.checkpoint.load()["phase"], "apply")
        with patch.object(self.runner, "_run_sync") as engine:
            _, error = self._analyze()
        self.assertIsInstance(error, CheckpointError)
        engine.assert_not_called()
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            new, error = self._analyze(restart=True)
        self.assertIsNone(error)
        self.assertNotEqual(analysis.staging_root, new.staging_root)
        archive = self.runner.checkpoint.root.parent / "safety-archives" / analysis.staging_root.name
        self.assertEqual((archive / "remote.txt").read_text(), "protected copy")

    def test_successful_apply_saves_config_and_baseline_before_removing_the_copy(self):
        with patch.object(self.runner, "_run_sync", side_effect=self._finish_download):
            analysis, error = self._analyze()
        self.assertIsNone(error)
        original_remove = self.runner._remove_stage

        def check_before_remove(path):
            self.assertTrue(ConfigStore(self.config.path).load()["safety"]["bootstrap_complete"])
            self.assertTrue((self.runner.checkpoint.root.parent / "safety-manifest.json").is_file())
            original_remove(path)

        with (
            patch.object(self.runner, "_run_sync"),
            patch.object(self.runner, "_remove_stage", side_effect=check_before_remove),
        ):
            result, error = self._execute(analysis)
        self.assertIsNone(error)
        self.assertEqual(result.synchronized_files, 1)
        self.assertEqual((self.local / "remote.txt").read_text(), "protected copy")
        self.assertFalse(self.runner.has_pending_operation)
        self.assertFalse(analysis.staging_root.exists())

    def test_inherited_lease_blocks_a_new_operation_until_the_engine_exits(self):
        with self.runner.checkpoint.lease() as lease:
            child = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                stdin=subprocess.PIPE, pass_fds=(lease,),
            )
        with child:
            with self.assertRaises(CheckpointError):
                with self.runner.checkpoint.lease():
                    self.fail("lease overlapped an existing engine")
            child.communicate(timeout=5)
        with self.runner.checkpoint.lease():
            pass

    def test_download_sample_excludes_journal_and_keeps_partial_bytes_separate(self):
        (self.root / ".sync_fixture.db").write_bytes(b"journal")
        (self.root / "regular.txt").write_bytes(b"done")
        (self.root / ".large.txt.~bcd34").write_bytes(b"partial")
        (self.root / "ignored.txt").write_bytes(b"ignored")
        (self.root / "link").symlink_to(self.root / "regular.txt")
        measured = measure_download(self.root, ExclusionMatcher(["ignored.txt"]), threading.Event())
        self.assertEqual(measured, (1, 4, 7))

    def test_final_verification_progress_counts_each_unique_path(self):
        stage = self.root / "stage"
        stage.mkdir()
        (stage / "common.txt").write_bytes(b"abc")
        (self.local / "common.txt").write_bytes(b"abc")
        (stage / "missing.txt").touch()
        (self.local / "extra.txt").touch()
        matcher = ExclusionMatcher([])
        progress = []
        differences = inventory_differences(
            scan_inventory(stage, matcher), scan_inventory(self.local, matcher),
            progress=BootstrapProgressReporter(progress.append),
        )
        self.assertEqual(differences, (("missing.txt",), ("extra.txt",), ()))
        self.assertEqual(progress[0].total_items, 3)
        self.assertEqual(progress[-1].items, 3)


if __name__ == "__main__":
    unittest.main()
