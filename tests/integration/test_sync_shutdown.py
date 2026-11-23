from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pynextcloud_sync.nextcloud.command import CommandSpec
from pynextcloud_sync.storage.log import AppLogger

try:
    from gi.repository import Gio, GLib
except ImportError:
    Gio = GLib = None


@unittest.skipIf(Gio is None, "GIO is unavailable")
class SyncShutdownTests(unittest.TestCase):
    def setUp(self) -> None:
        from pynextcloud_sync.core.sync_engine import SyncEngine

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.logger = AppLogger(Path(self.directory.name) / "test.log", save_to_disk=False)
        self.addCleanup(self.logger.close)
        self.engine = SyncEngine(self.logger)
        self.engine.OUTPUT_DRAIN_SECONDS = 1
        self.engine.CANCEL_GRACE_SECONDS = 1

    def wait(self, ready, timeout=5):
        deadline = time.monotonic() + timeout
        context = GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if ready():
                return
            time.sleep(0.01)
        self.fail("The subprocess did not complete in time")

    def start(self, program):
        results = []
        self.engine.run(CommandSpec((sys.executable, "-c", program), {}), results.append)
        return results

    def test_exit_releases_state_even_when_a_descendant_holds_the_output_pipe(self):
        marker = Path(self.directory.name) / "child"
        program = (
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
            f"Path({str(marker)!r}).write_text(str(child.pid))\n"
            "print('completed', flush=True)\n"
        )
        results = self.start(program)
        try:
            self.wait(lambda: bool(results))
            self.assertFalse(self.engine.running)
            self.assertTrue(results[0].successful)
            self.assertIn("completed", results[0].output)
            self.assertEqual(len(results), 1)
        finally:
            if marker.exists():
                try:
                    os.kill(int(marker.read_text()), 15)
                except ProcessLookupError:
                    pass

    def test_explicit_cancellation_reaps_a_process_that_ignores_sigterm(self):
        results = self.start(
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('ready', flush=True)\n"
            "time.sleep(20)\n"
        )
        self.wait(lambda: any(line.endswith("CMD ready") for line in self.logger.recent_lines()))
        process = self.engine.process
        self.engine.cancel()
        self.engine.cancel()
        self.wait(lambda: bool(results))
        self.assertIsNone(process.get_identifier())
        self.assertFalse(self.engine.running)
        self.assertTrue(results[0].interrupted)
        self.assertFalse(results[0].successful)
        self.assertEqual(self.engine._cancel_source, 0)
        self.assertEqual(self.engine._output_drain_source, 0)
        self.assertEqual(len(results), 1)

    def test_zero_exit_after_sigterm_is_still_an_interrupted_run(self):
        results = self.start(
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
            "print('ready', flush=True)\n"
            "time.sleep(20)\n"
        )
        self.wait(lambda: any(line.endswith("CMD ready") for line in self.logger.recent_lines()))
        self.engine.cancel()
        self.wait(lambda: bool(results))
        self.assertEqual(results[0].exit_code, 0)
        self.assertTrue(results[0].interrupted)
        self.assertFalse(results[0].successful)

    def test_output_processing_failure_always_reports_completion(self):
        from pynextcloud_sync.nextcloud.activity import ActivityCapture

        with patch.object(ActivityCapture, "feed", side_effect=ValueError("fixture failure")):
            results = self.start("import time\nprint('ready', flush=True)\ntime.sleep(20)\n")
            self.wait(lambda: bool(results))
        self.assertFalse(self.engine.running)
        self.assertTrue(results[0].interrupted)
        self.assertFalse(results[0].successful)
        self.assertEqual(len(results), 1)
