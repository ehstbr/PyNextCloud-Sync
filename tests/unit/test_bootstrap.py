from __future__ import annotations

import os
import tempfile
import types
import unittest
from pathlib import Path

from pynextcloud_sync.core.bootstrap import (
    BootstrapAnalysis,
    BootstrapPolicy,
    BootstrapRunner,
    analyze_inventories,
    inventory_differences,
)
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


if __name__ == "__main__":
    unittest.main()
