from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.storage.config import (
    DEFAULT_CONFIG,
    ConfigStore,
    ConfigurationError,
    normalize_server_url,
    validate_config,
)


class ConfigTests(unittest.TestCase):
    def test_normalizes_server_url(self) -> None:
        self.assertEqual(
            normalize_server_url(" HTTPS://cloud.example.com/nextcloud/ "),
            "https://cloud.example.com/nextcloud",
        )

    def test_rejects_credentials_in_url(self) -> None:
        with self.assertRaises(ConfigurationError):
            normalize_server_url("https://user:secret@cloud.example.com")

    def test_unknown_newer_schema_is_not_discarded(self) -> None:
        data = copy.deepcopy(DEFAULT_CONFIG)
        data["schema_version"] = 999
        with self.assertRaises(ConfigurationError):
            validate_config(data)

    def test_rejects_proxy_credentials(self) -> None:
        data = copy.deepcopy(DEFAULT_CONFIG)
        data["network"]["custom_proxy"] = "http://user:secret@proxy.example.com:8080"
        with self.assertRaises(ConfigurationError):
            validate_config(data)

    def test_logging_defaults_are_merged_into_existing_configuration(self) -> None:
        validated = validate_config({"schema_version": 1})
        self.assertTrue(validated["logging"]["save_logs"])
        self.assertEqual(validated["logging"]["retention_days"], 30)
        self.assertFalse(validated["safety"]["bootstrap_complete"])
        self.assertTrue(validated["safety"]["guard_enabled"])

    def test_rejects_invalid_safety_threshold(self) -> None:
        data = copy.deepcopy(DEFAULT_CONFIG)
        data["safety"]["deletion_percent_threshold"] = 0
        with self.assertRaises(ConfigurationError):
            validate_config(data)

    def test_rejects_invalid_log_retention(self) -> None:
        data = copy.deepcopy(DEFAULT_CONFIG)
        data["logging"]["retention_days"] = 0
        with self.assertRaises(ConfigurationError):
            validate_config(data)

    def test_atomic_store_contains_no_secret_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = ConfigStore(path)
            store.data = copy.deepcopy(DEFAULT_CONFIG)
            store.data["account"] = {
                "server_url": "https://cloud.example.com",
                "login_name": "alice",
                "authentication_type": "browser",
                "local_root": str(Path(directory) / "NextCloud"),
            }
            store.save()
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("appPassword", raw)
            self.assertNotIn('"password"', raw.lower())
            self.assertEqual(json.loads(raw)["account"]["login_name"], "alice")


if __name__ == "__main__":
    unittest.main()
