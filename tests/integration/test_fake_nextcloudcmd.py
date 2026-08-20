from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from pynextcloud_sync.nextcloud.command import build_command, classify_output


class FakeNextcloudCmdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fake = Path(__file__).parents[1] / "fixtures" / "fake_nextcloudcmd.py"

    def _run(self, mode: str) -> subprocess.CompletedProcess[str]:
        spec = build_command(
            {
                "server_url": "https://cloud.example.com",
                "login_name": "alice",
                "local_root": "/tmp/NextCloud",
            },
            {"max_sync_retries": 3, "detailed_output": True},
            {"custom_proxy": None, "trust_invalid_certificates": False},
            "integration-secret",
            executable=str(self.fake),
        )
        environment = os.environ.copy()
        environment.update(spec.environment)
        environment["FAKE_NEXTCLOUDCMD_MODE"] = mode
        return subprocess.run(
            spec.argv,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=5,
        )

    def test_success(self) -> None:
        result = self._run("success")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(classify_output(result.stdout, result.returncode), "success")
        self.assertNotIn("integration-secret", result.stdout)

    def test_authentication_failure(self) -> None:
        result = self._run("auth-failure")
        self.assertEqual(classify_output(result.stdout, result.returncode), "authentication")

    def test_conflict_surface(self) -> None:
        result = self._run("conflict")
        self.assertEqual(classify_output(result.stdout, result.returncode), "conflict")


if __name__ == "__main__":
    unittest.main()

