from __future__ import annotations

import unittest

from pynextcloud_sync.nextcloud.push_protocol import (
    parse_push_capability,
    validate_push_transport,
)


class PushProtocolTests(unittest.TestCase):
    def test_parses_capabilities(self) -> None:
        payload = {
            "ocs": {
                "data": {
                    "capabilities": {
                        "notify_push": {
                            "endpoints": {
                                "websocket": "wss://cloud.example.com/push/ws",
                                "pre_auth": "https://cloud.example.com/apps/notify_push/pre_auth",
                            }
                        }
                    }
                }
            }
        }
        endpoints = parse_push_capability(payload)
        self.assertEqual(endpoints.websocket, "wss://cloud.example.com/push/ws")
        self.assertIn("pre_auth", endpoints.pre_auth)

    def test_rejects_tls_downgrade(self) -> None:
        with self.assertRaises(ValueError):
            validate_push_transport("https://cloud.example.com", "ws://cloud.example.com/push/ws")


if __name__ == "__main__":
    unittest.main()

