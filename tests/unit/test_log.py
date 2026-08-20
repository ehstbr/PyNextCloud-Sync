from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.storage.log import AppLogger


class LogTests(unittest.TestCase):
    def test_numeric_format_arguments_remain_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = AppLogger(Path(directory) / "test.log", save_to_disk=False)
            received: list[str] = []
            logger.subscribe(received.append)
            logger.info("Finished after %.1f seconds with code %s", 8.623, 0)
            self.assertIn("Finished after 8.6 seconds with code 0", received[-1])
            logger.close()

    def test_creates_one_file_per_day_and_prunes_by_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = [dt.date(2026, 8, 5)]
            logger = AppLogger(
                Path(directory) / "test.log",
                save_to_disk=True,
                retention_days=2,
                date_provider=lambda: current[0],
            )
            for day in (5, 6, 7):
                current[0] = dt.date(2026, 8, day)
                logger.info("Day %s", day)
            logger.close()
            names = sorted(path.name for path in Path(directory).glob("test-*.log"))
            self.assertEqual(names, ["test-2026-08-06.log", "test-2026-08-07.log"])

    def test_can_disable_persistent_files_without_disabling_live_activity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = AppLogger(Path(directory) / "test.log", save_to_disk=False)
            received: list[str] = []
            logger.subscribe(received.append)
            logger.info("Live only")
            self.assertTrue(received)
            self.assertIn("Live only", logger.tail(500))
            self.assertEqual(list(Path(directory).glob("test-*.log")), [])
            logger.close()

    def test_tail_reads_only_the_requested_end_of_daily_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "test-2026-08-06.log"
            second = root / "test-2026-08-07.log"
            first.write_text(
                "\n".join(f"old-{index}" for index in range(10_000)) + "\n",
                encoding="utf-8",
            )
            second.write_text(
                "\n".join(f"new-{index}" for index in range(20)) + "\n",
                encoding="utf-8",
            )
            logger = AppLogger(root / "test.log", save_to_disk=True)
            tail = logger.tail(25).splitlines()
            self.assertEqual(tail[:5], [f"old-{index}" for index in range(9_995, 10_000)])
            self.assertEqual(tail[-20:], [f"new-{index}" for index in range(20)])
            logger.close()

    def test_single_file_legacy_log_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.log").write_text("legacy entry\n", encoding="utf-8")
            logger = AppLogger(root / "test.log", save_to_disk=True)
            self.assertNotIn("legacy entry", logger.tail(10))
            logger.close()


if __name__ == "__main__":
    unittest.main()
