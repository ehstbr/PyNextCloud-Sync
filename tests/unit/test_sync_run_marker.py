from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.core.sync_run_marker import SyncRunMarker


class SyncRunMarkerTests(unittest.TestCase):
    def _account(self, root: Path) -> dict[str, str]:
        return {
            "server_url": "https://cloud.example.com",
            "login_name": "alice",
            "local_root": str(root),
        }

    def test_marker_survives_until_explicit_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            account = self._account(base / "NextCloud")
            marker = SyncRunMarker(base / "sync-run.json")
            marker.begin(account)
            self.assertTrue(marker.pending_for(account))
            marker.clear()
            self.assertFalse(marker.pending_for(account))

    def test_invalid_existing_marker_is_treated_as_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            account = self._account(base / "NextCloud")
            path = base / "sync-run.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertTrue(SyncRunMarker(path).pending_for(account))


if __name__ == "__main__":
    unittest.main()
