from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.nextcloud.models import AccountDetails, ServerDetails
from pynextcloud_sync.storage.config import ConfigStore
from pynextcloud_sync.storage.remote_details import (
    cached_account_details,
    cached_server_details,
    cached_storage_usage,
    store_account_details,
    store_server_details,
    store_storage_usage,
)


class RemoteDetailsTests(unittest.TestCase):
    def test_account_server_and_storage_details_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = ConfigStore(path)
            account = AccountDetails("Alice", "alice@example.com", 10, 100)
            server = ServerDetails("Nextcloud", "34.0.1", False, False)

            store_account_details(store, account)
            store_server_details(store, server)

            reloaded = ConfigStore(path)
            reloaded.load()
            self.assertEqual(cached_account_details(reloaded), account)
            self.assertEqual(cached_server_details(reloaded), server)
            storage = cached_storage_usage(reloaded)
            self.assertIsNotNone(storage)
            self.assertEqual((storage.used, storage.total), (10, 100))

    def test_post_sync_storage_update_preserves_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "settings.json")
            account = AccountDetails("Alice", "alice@example.com", 10, 100)
            store_account_details(store, account)

            store_storage_usage(store, 25, 100)

            reloaded = ConfigStore(store.path)
            reloaded.load()
            cached_account = cached_account_details(reloaded)
            self.assertIsNotNone(cached_account)
            self.assertEqual(cached_account.display_name, "Alice")
            self.assertEqual(cached_account.email, "alice@example.com")
            storage = cached_storage_usage(reloaded)
            self.assertIsNotNone(storage)
            self.assertEqual((storage.used, storage.total), (25, 100))

    def test_account_reset_clears_remote_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "settings.json")
            store_account_details(store, AccountDetails("Alice", "", 10, -3))
            store_server_details(
                store, ServerDetails("Nextcloud", "34.0.1", False, False)
            )

            store.reset_account()

            self.assertIsNone(cached_account_details(store))
            self.assertIsNone(cached_storage_usage(store))
            self.assertIsNone(cached_server_details(store))


if __name__ == "__main__":
    unittest.main()
