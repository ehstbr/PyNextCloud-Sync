from __future__ import annotations

import unittest

from pynextcloud_sync.nextcloud.command import (
    BoundedOutputCapture,
    build_command,
    classify_output,
)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = {
            "server_url": "https://cloud.example.com",
            "login_name": "alice",
            "local_root": "/tmp/NextCloud",
        }
        self.sync = {"max_sync_retries": 3, "detailed_output": True}
        self.network = {"custom_proxy": None, "trust_invalid_certificates": False}

    def test_secret_is_only_in_environment(self) -> None:
        spec = build_command(
            self.account, self.sync, self.network, "very-secret", executable="/bin/true"
        )
        self.assertNotIn("very-secret", spec.argv)
        self.assertEqual(spec.environment["NC_PASSWORD"], "very-secret")
        self.assertIn("--non-interactive", spec.argv)
        self.assertIn("-h", spec.argv)

    def test_options_map_without_shell(self) -> None:
        network = {"custom_proxy": "http://proxy:8080", "trust_invalid_certificates": True}
        sync = {"max_sync_retries": 7, "detailed_output": False}
        spec = build_command(self.account, sync, network, "secret", executable="/bin/true")
        self.assertIn("--silent", spec.argv)
        self.assertIn("--trust", spec.argv)
        self.assertIn("--httpproxy", spec.argv)

    def test_result_classification(self) -> None:
        self.assertEqual(classify_output("", 0), "success")
        self.assertEqual(classify_output("authentication failed", 4), "authentication")
        self.assertEqual(classify_output("created conflicted copy", 0), "conflict")
        self.assertEqual(classify_output("server failure", 5), "sync_error")

    def test_large_output_keeps_a_bounded_tail_without_losing_classification(self) -> None:
        capture = BoundedOutputCapture(max_lines=20)
        capture.feed("authentication failed")
        for index in range(100_000):
            capture.feed(f"ordinary output line {index}")

        self.assertEqual(capture.classification(4), "authentication")
        self.assertNotIn("ordinary output line 0\n", capture.output)
        self.assertEqual(len(capture.output.splitlines()), 20)


if __name__ == "__main__":
    unittest.main()
