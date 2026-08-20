from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pynextcloud_sync.core.state import AppState, StateController
from pynextcloud_sync.core.triggers import Trigger


SCHEDULER_SOURCE = (
    Path(__file__).parents[2] / "src" / "pynextcloud_sync" / "core" / "scheduler.py"
)


class FakeGLib:
    SOURCE_REMOVE = False
    SOURCE_CONTINUE = True
    callbacks: dict[int, object] = {}
    next_id = 1

    @classmethod
    def _add(cls, callback: object) -> int:
        source_id = cls.next_id
        cls.next_id += 1
        cls.callbacks[source_id] = callback
        return source_id

    @classmethod
    def idle_add(cls, callback: object) -> int:
        return cls._add(callback)

    @classmethod
    def timeout_add(cls, _milliseconds: int, callback: object, *args: object) -> int:
        return cls._add(lambda: callback(*args))

    @classmethod
    def timeout_add_seconds(cls, _seconds: int, callback: object, *args: object) -> int:
        return cls._add(lambda: callback(*args))

    @classmethod
    def source_remove(cls, source_id: int) -> None:
        cls.callbacks.pop(source_id, None)

    @classmethod
    def run_source(cls, source_id: int) -> object:
        callback = cls.callbacks.pop(source_id)
        return callback()


class FakeCredentials:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def lookup(self, _server: str, _username: str, callback: object) -> None:
        self.callbacks.append(callback)


class FakeEngine:
    def __init__(self) -> None:
        self.running = False
        self.runs: list[tuple[object, object]] = []
        self.cancelled = False

    def run(self, spec: object, callback: object) -> None:
        if self.running:
            raise RuntimeError("overlapping process")
        self.running = True
        self.runs.append((spec, callback))

    def cancel(self) -> None:
        self.cancelled = True


class FakeLogger:
    def add_secret(self, *_args: object) -> None:
        pass

    def info(self, *_args: object) -> None:
        pass

    def error(self, *_args: object) -> None:
        pass

    def warning(self, *_args: object) -> None:
        pass


def load_scheduler_module():
    FakeGLib.callbacks = {}
    FakeGLib.next_id = 1
    fake_gi = types.ModuleType("gi")
    fake_repository = types.ModuleType("gi.repository")
    fake_repository.GLib = FakeGLib
    fake_credentials = types.ModuleType("pynextcloud_sync.nextcloud.credentials")
    fake_credentials.KeyringLockedError = type("KeyringLockedError", (RuntimeError,), {})
    fake_sync_engine = types.ModuleType("pynextcloud_sync.core.sync_engine")
    fake_sync_engine.SyncEngine = FakeEngine
    fake_sync_engine.SyncResult = object
    spec = importlib.util.spec_from_file_location(
        "pynextcloud_sync.core.scheduler_test_double", SCHEDULER_SOURCE
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "gi": fake_gi,
            "gi.repository": fake_repository,
            "pynextcloud_sync.nextcloud.credentials": fake_credentials,
            "pynextcloud_sync.core.sync_engine": fake_sync_engine,
        },
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    module.build_command = lambda *_args, **_kwargs: object()
    return module


class SchedulerTests(unittest.TestCase):
    def _config(self) -> object:
        return types.SimpleNamespace(
            data={
                "account": {
                    "server_url": "https://cloud.example.com",
                    "login_name": "alice",
                    "local_root": "/tmp/NextCloud",
                },
                "sync": {
                    "local_inotify_enabled": True,
                    "local_interval_enabled": False,
                    "remote_push_enabled": True,
                    "remote_interval_enabled": True,
                    "exclude_patterns": [],
                    "exclude_patterns_enabled": True,
                },
                "network": {},
                "runtime": {},
            }
        )

    def test_credential_preparation_coalesces_new_triggers(self) -> None:
        module = load_scheduler_module()
        credentials = FakeCredentials()
        engine = FakeEngine()
        scheduler = module.SyncScheduler(
            self._config(),
            credentials,
            engine,
            StateController(AppState.IDLE_OK),
            FakeLogger(),
        )

        scheduler.request(Trigger.MANUAL)
        first_source = scheduler._start_source
        scheduler.request(Trigger.REMOTE_INTERVAL)
        self.assertEqual(scheduler._start_source, first_source)
        FakeGLib.run_source(first_source)
        self.assertEqual(len(credentials.callbacks), 1)

        scheduler.request(Trigger.LOCAL_INOTIFY)
        self.assertEqual(len(credentials.callbacks), 1)
        credentials.callbacks[0]("secret", None)

        self.assertEqual(len(engine.runs), 1)
        self.assertTrue(scheduler.queue)

    def test_stop_removes_pending_sources_and_cancels_a_process(self) -> None:
        module = load_scheduler_module()
        engine = FakeEngine()
        scheduler = module.SyncScheduler(
            self._config(),
            FakeCredentials(),
            engine,
            StateController(AppState.IDLE_OK),
            FakeLogger(),
        )
        scheduler.request(Trigger.MANUAL)
        engine.running = True
        scheduler.stop()
        self.assertFalse(FakeGLib.callbacks)
        self.assertTrue(engine.cancelled)

    def test_locked_keyring_defers_automatic_triggers_until_manual_unlock(self) -> None:
        module = load_scheduler_module()
        credentials = FakeCredentials()
        engine = FakeEngine()
        state = StateController(AppState.IDLE_OK)
        scheduler = module.SyncScheduler(
            self._config(), credentials, engine, state, FakeLogger()
        )

        scheduler.request(Trigger.STARTUP)
        FakeGLib.run_source(scheduler._start_source)
        credentials.callbacks[0](None, module.KeyringLockedError("cancelled"))

        self.assertTrue(scheduler.keyring_locked)
        self.assertEqual(state.snapshot.state, AppState.KEYRING_LOCKED)

        scheduler.request(Trigger.LOCAL_INOTIFY)
        scheduler.request(Trigger.REMOTE_INTERVAL)
        self.assertEqual(len(credentials.callbacks), 1)
        self.assertTrue(scheduler.queue)

        scheduler.request(Trigger.MANUAL)
        self.assertEqual(len(credentials.callbacks), 2)
        credentials.callbacks[1]("secret", None)

        self.assertFalse(scheduler.keyring_locked)
        self.assertEqual(len(engine.runs), 1)

    def test_rejected_authentication_blocks_retries_until_reconnected(self) -> None:
        module = load_scheduler_module()
        credentials = FakeCredentials()
        state = StateController(AppState.IDLE_OK)
        scheduler = module.SyncScheduler(
            self._config(), credentials, FakeEngine(), state, FakeLogger()
        )
        scheduler._authentication_required = True

        scheduler.request(Trigger.LOCAL_INOTIFY)

        self.assertTrue(scheduler.authentication_required)
        self.assertEqual(state.snapshot.state, AppState.AUTH_REQUIRED)
        self.assertEqual(credentials.callbacks, [])
        self.assertTrue(scheduler.queue)

        scheduler.authentication_restored()
        self.assertFalse(scheduler.authentication_required)


if __name__ == "__main__":
    unittest.main()
