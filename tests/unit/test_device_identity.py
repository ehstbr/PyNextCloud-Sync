from __future__ import annotations

import unittest

from pynextcloud_sync.nextcloud.device_identity import (
    authorization_name,
    normalized_device_name,
)


class DeviceIdentityTests(unittest.TestCase):
    def test_authorization_name_is_stable_and_does_not_include_the_version(self) -> None:
        self.assertEqual(
            authorization_name("Loja PC"),
            "PyNextCloud-Sync (Loja-PC)",
        )
        self.assertNotIn("0.1.", authorization_name("Loja PC"))

    def test_device_name_is_sanitized_for_an_http_user_agent(self) -> None:
        self.assertEqual(normalized_device_name("  ThinkPad / T490  "), "ThinkPad-T490")
        self.assertEqual(normalized_device_name("áéí"), "Linux-device")

    def test_device_name_has_a_bounded_length(self) -> None:
        self.assertLessEqual(len(normalized_device_name("x" * 200)), 48)


if __name__ == "__main__":
    unittest.main()
