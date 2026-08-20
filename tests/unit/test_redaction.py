from __future__ import annotations

import unittest

from pynextcloud_sync.util.redact import Redactor


class RedactionTests(unittest.TestCase):
    def test_redacts_registered_and_url_secrets(self) -> None:
        redactor = Redactor(["secret-value"])
        text = redactor.redact(
            "secret-value https://alice:password@example.com?a=1&token=abc Authorization: Bearer xyz"
        )
        for secret in ("secret-value", "password", "abc", "xyz"):
            self.assertNotIn(secret, text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()

