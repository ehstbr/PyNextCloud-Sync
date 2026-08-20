from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

INOTIFY_SOURCE = Path(__file__).parents[2] / "src" / "pynextcloud_sync" / "core" / "inotify.py"


def load_inotify_module():
    fake_gi = types.ModuleType("gi")
    fake_repository = types.ModuleType("gi.repository")
    fake_repository.GLib = types.SimpleNamespace()
    spec = importlib.util.spec_from_file_location(
        "pynextcloud_sync.core.inotify_test_double", INOTIFY_SOURCE
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": fake_repository}):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class _Matcher:
    def matches_name(self, _name: str) -> bool:
        return False


class _Logger:
    def debug(self, *_args: object) -> None:
        pass

    def warning(self, *_args: object) -> None:
        pass


class InotifyOverflowTests(unittest.TestCase):
    def test_overflow_is_not_discarded_as_unknown_watch_descriptor(self) -> None:
        module = load_inotify_module()
        watcher = object.__new__(module.InotifyWatcher)
        watcher.watches = {}
        watcher.matcher = _Matcher()
        watcher.logger = _Logger()
        watcher.on_change = lambda _path: self.fail("overflow must not become a normal change")
        data = module.EVENT_STRUCT.pack(-1, module.IN_Q_OVERFLOW, 0, 0)
        with self.assertRaises(module.InotifyOverflowError):
            watcher._parse(data)


if __name__ == "__main__":
    unittest.main()
