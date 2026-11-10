from __future__ import annotations

import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pynextcloud_sync.util.redact import Redactor


class SyncEngineOutputTests(unittest.TestCase):
    def test_output_is_redacted_and_completion_is_dispatched_to_the_main_loop(self):
        fake_gi = types.ModuleType("gi")
        repository = types.ModuleType("gi.repository")
        callbacks = []
        repository.GLib = types.SimpleNamespace(
            Error=RuntimeError, SOURCE_REMOVE=False, idle_add=lambda *args: callbacks.append(args)
        )
        repository.Gio = types.SimpleNamespace()
        source = Path(__file__).parents[2] / "src/pynextcloud_sync/core/sync_engine.py"
        spec = importlib.util.spec_from_file_location("sync_engine_test_double", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "gi": fake_gi, "gi.repository": repository, spec.name: module,
        }):
            spec.loader.exec_module(module)

        logger = Mock(redactor=Redactor(["fixture-password"]))
        engine = module.SyncEngine(logger)
        stream = Mock()
        stream.read_bytes.side_effect = [
            types.SimpleNamespace(get_data=lambda: b"first\r\n\nfixture-pass"),
            types.SimpleNamespace(get_data=lambda: b"word\ninvalid-\xff\nlast"),
            types.SimpleNamespace(get_data=lambda: b""),
        ]
        process = Mock()
        process.get_stdout_pipe.return_value = stream
        process.get_if_exited.return_value = True
        process.get_exit_status.return_value = 0
        engine.process = process
        done = Mock()

        engine._collect(process, time.monotonic(), done)

        stream.close.assert_called_once_with(None)
        process.wait.assert_called_once_with(None)
        done.assert_not_called()
        self.assertTrue(engine.running)
        self.assertEqual(len(callbacks), 1)
        dispatch, *args = callbacks[0]
        self.assertFalse(dispatch(*args))
        result = done.call_args.args[0]
        self.assertTrue(result.successful)
        self.assertFalse(engine.running)
        self.assertEqual(result.output, "first\n\n[REDACTED]\ninvalid-\ufffd\nlast")


if __name__ == "__main__":
    unittest.main()
