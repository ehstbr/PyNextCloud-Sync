from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.safety import (
    SafetyAlert,
    SafetyGuard,
    SafetyManifest,
    scan_inventory,
)


class FakeLogger:
    def info(self, *_args: object) -> None:
        pass

    def error(self, *_args: object) -> None:
        pass


class SafetyGuardTests(unittest.TestCase):
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
                },
                "safety": {
                    "guard_enabled": True,
                    "deletion_count_threshold": 10,
                    "deletion_percent_threshold": 20,
                },
            }
        )

    def test_empty_previously_populated_folder_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "NextCloud"
            root.mkdir()
            for index in range(3):
                (root / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
            (root / ".sync_test.db").touch()
            config = self._config(root)
            manifest = SafetyManifest(Path(directory) / "manifest.json")
            manifest.save(config.data["account"], scan_inventory(root, ExclusionMatcher([])))

            for item in root.glob("file-*.txt"):
                item.unlink()
            alert = SafetyGuard(config, FakeLogger(), manifest).check()

            self.assertIsNotNone(alert)
            self.assertEqual(alert.reason, "folder_emptied")
            self.assertEqual(alert.previous_files, 3)
            self.assertEqual(alert.current_files, 0)

    def test_mass_deletion_uses_count_or_percentage_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "NextCloud"
            root.mkdir()
            for index in range(20):
                (root / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
            config = self._config(root)
            manifest = SafetyManifest(Path(directory) / "manifest.json")
            manifest.save(config.data["account"], scan_inventory(root, ExclusionMatcher([])))

            for index in range(4):
                (root / f"file-{index}.txt").unlink()
            alert = SafetyGuard(config, FakeLogger(), manifest).check()

            self.assertIsNotNone(alert)
            self.assertEqual(alert.reason, "mass_local_deletion")
            self.assertEqual(alert.missing_count, 4)

    def test_small_change_below_both_limits_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "NextCloud"
            root.mkdir()
            for index in range(100):
                (root / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
            config = self._config(root)
            manifest = SafetyManifest(Path(directory) / "manifest.json")
            manifest.save(config.data["account"], scan_inventory(root, ExclusionMatcher([])))

            (root / "file-0.txt").unlink()

            self.assertIsNone(SafetyGuard(config, FakeLogger(), manifest).check())

    def test_replaced_folder_identity_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "NextCloud"
            root.mkdir()
            (root / "important.txt").write_text("data", encoding="utf-8")
            config = self._config(root)
            manifest = SafetyManifest(Path(directory) / "manifest.json")
            manifest.save(config.data["account"], scan_inventory(root, ExclusionMatcher([])))

            (root / "important.txt").unlink()
            root.rmdir()
            root.mkdir()
            (root / "important.txt").write_text("different", encoding="utf-8")
            alert = SafetyGuard(config, FakeLogger(), manifest).check()

            self.assertIsNotNone(alert)
            self.assertEqual(alert.reason, "folder_replaced")

    def test_missing_sync_database_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "NextCloud"
            root.mkdir()
            (root / "important.txt").write_text("data", encoding="utf-8")
            database = root / ".sync_test.db"
            database.touch()
            config = self._config(root)
            manifest = SafetyManifest(Path(directory) / "manifest.json")
            manifest.save(config.data["account"], scan_inventory(root, ExclusionMatcher([])))

            database.unlink()
            alert = SafetyGuard(config, FakeLogger(), manifest).check()

            self.assertIsNotNone(alert)
            self.assertEqual(alert.reason, "database_missing")

    def test_only_explicit_deletion_alerts_can_be_approved_once(self) -> None:
        self.assertTrue(SafetyAlert("folder_emptied", "blocked").can_approve_once)
        self.assertTrue(SafetyAlert("mass_local_deletion", "blocked").can_approve_once)
        for reason in (
            "account_changed",
            "database_missing",
            "folder_missing",
            "folder_replaced",
            "guard_failed",
            "manifest_missing",
            "scan_failed",
        ):
            with self.subTest(reason=reason):
                self.assertFalse(SafetyAlert(reason, "blocked").can_approve_once)


if __name__ == "__main__":
    unittest.main()
