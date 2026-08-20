from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeSecretError(Exception):
    pass


class FakeSchema:
    @staticmethod
    def new(name, flags, attributes):
        return name, flags, attributes


class FakeSecretValue:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_text(self) -> str:
        return self.value


class FakeVariant:
    def __init__(self, _signature, value=None) -> None:
        self.value = _signature if value is None else value

    def unpack(self):
        return self.value

    def get_child_value(self, index: int):
        return FakeVariant(self.value[index])

    def lookup_value(self, key, _variant_type):
        return self.value.get(key)


class FakeVariantType:
    @staticmethod
    def new(signature: str) -> str:
        return signature


class FakeGio:
    DBusCallFlags = types.SimpleNamespace(NONE=0)


class FakeSecretItem:
    def __init__(self, key: tuple[str, str], stale: bool = False) -> None:
        self.key = key
        self.stale = stale

    def load_secret_sync(self, _cancellable) -> bool:
        if self.stale:
            raise FakeSecretError(
                "g-dbus-error-quark: No such secret item at path: "
                "/org/freedesktop/secrets/collection/login/12 (19)"
            )
        return not FakeSecret.locked

    def get_locked(self) -> bool:
        return FakeSecret.locked

    def get_secret(self):
        if FakeSecret.locked:
            return None
        value = FakeSecret.saved.get(self.key)
        return FakeSecretValue(value) if value is not None else None


class FakeSecretCollection:
    @staticmethod
    def for_alias_sync(_service, alias, flags, _cancellable):
        FakeSecret.collection_aliases.append(alias)
        FakeSecret.collection_flags.append(flags)
        if FakeSecret.default_collection_missing:
            return None
        return FakeSecretCollection()

    def get_locked(self) -> bool:
        return FakeSecret.locked


class FakeSecretService:
    @staticmethod
    def disconnect():
        FakeSecret.disconnects += 1
        if FakeSecret.pending_store is not None:
            key, password, schema = FakeSecret.pending_store
            FakeSecret.saved[key] = password
            FakeSecret.saved_schema = schema[0]
            FakeSecret.pending_store = None

    @staticmethod
    def get_sync(flags, _cancellable):
        FakeSecret.service_flags.append(flags)
        if FakeSecret.failure:
            raise FakeSecret.failure
        return FakeSecretService()

    def search_sync(self, _schema, attributes, flags, _cancellable):
        FakeSecret.operations.append(("search", attributes))
        FakeSecret.search_schemas.append(_schema)
        FakeSecret.search_flags.append(flags)
        if FakeSecret.stale_search_failures and (
            FakeSecret.stale_search_schema is None
            or _schema == FakeSecret.stale_search_schema
        ):
            FakeSecret.stale_search_failures -= 1
            raise FakeSecretError(
                "g-dbus-error-quark: No such secret item at path: "
                "/org/freedesktop/secrets/collection/login/12 (19)"
            )
        if FakeSecret.failure:
            raise FakeSecret.failure
        key = (attributes["server"], attributes["username"])
        saved_matches_schema = key in FakeSecret.saved and (
            FakeSecret.saved_schema is None or _schema == FakeSecret.saved_schema
        )
        stale_matches_schema = FakeSecret.include_stale_item and (
            FakeSecret.stale_schema is None or _schema == FakeSecret.stale_schema
        )
        if not saved_matches_schema and not stale_matches_schema:
            return []
        if FakeSecret.hide_items_while_locked and FakeSecret.locked:
            return []
        if FakeSecret.locked and flags & FakeSecret.SearchFlags.UNLOCK:
            FakeSecret.unlock_attempts += 1
            if not FakeSecret.unlock_cancelled:
                FakeSecret.locked = False
        items = []
        if stale_matches_schema:
            items.append(FakeSecretItem(key, stale=True))
        if saved_matches_schema:
            items.append(FakeSecretItem(key))
        return items

    def call_sync(self, method, parameters, _flags, _timeout, _cancellable):
        if method == "SearchItems":
            attributes = parameters.unpack()[0]
            schema_name = attributes["xdg:schema"]
            FakeSecret.operations.append(("search", attributes))
            FakeSecret.search_schemas.append(schema_name)
            if FakeSecret.stale_search_failures and (
                FakeSecret.stale_search_schema is None
                or schema_name == FakeSecret.stale_search_schema
            ):
                FakeSecret.stale_search_failures -= 1
                raise FakeSecretError(
                    "g-dbus-error-quark: No such secret item at path: "
                    "/org/freedesktop/secrets/collection/login/12 (19)"
                )
            key = (attributes["server"], attributes["username"])
            saved_matches = key in FakeSecret.saved and (
                FakeSecret.saved_schema is None
                or schema_name == FakeSecret.saved_schema
            )
            stale_matches = FakeSecret.include_stale_item and (
                FakeSecret.stale_schema is None
                or schema_name == FakeSecret.stale_schema
            )
            paths = []
            if stale_matches:
                paths.append("/org/freedesktop/secrets/collection/login/12")
            if saved_matches:
                valid_path = "/org/freedesktop/secrets/collection/login/14"
                paths.append(valid_path)
                FakeSecret.path_passwords[valid_path] = FakeSecret.saved[key]
            return FakeVariant(([], paths) if FakeSecret.locked else (paths, []))
        if method == "GetSecrets":
            path = parameters.unpack()[0][0]
            if FakeSecret.locked:
                return FakeVariant(({},))
            if path.endswith("/12"):
                raise FakeSecretError(
                    "g-dbus-error-quark: No such secret item at path: "
                    f"{path} (19)"
                )
            password = FakeSecret.path_passwords.get(path)
            payload = {path: FakeSecretValue(password)} if password else {}
            return FakeVariant((payload,))
        raise AssertionError(method)

    def get_session_dbus_path(self):
        return "/org/freedesktop/secrets/session/s1"

    def decode_dbus_secret(self, value):
        return value

    def unlock_sync(self, objects, _cancellable):
        FakeSecret.unlock_operations.append(tuple(objects))
        FakeSecret.unlock_attempts += 1
        if not FakeSecret.unlock_cancelled:
            FakeSecret.locked = False
            count = (
                FakeSecret.unlock_report_count
                if FakeSecret.unlock_report_count is not None
                else 1
            )
            return count, list(objects) if count else []
        return 0, []


class FakeSecret:
    Schema = FakeSchema
    SchemaFlags = types.SimpleNamespace(NONE=0)
    SchemaAttributeType = types.SimpleNamespace(STRING="string")
    Service = FakeSecretService
    Collection = FakeSecretCollection
    ServiceFlags = types.SimpleNamespace(NONE=0, OPEN_SESSION=1, LOAD_COLLECTIONS=2)
    CollectionFlags = types.SimpleNamespace(NONE=0, LOAD_ITEMS=1)
    SearchFlags = types.SimpleNamespace(NONE=0, ALL=1, UNLOCK=2, LOAD_SECRETS=4)
    COLLECTION_DEFAULT = "default"
    saved: dict[tuple[str, str], str] = {}
    operations: list[tuple[str, dict[str, str]]] = []
    service_flags: list[int] = []
    search_flags: list[int] = []
    search_schemas: list[object] = []
    store_schemas: list[object] = []
    clear_schemas: list[object] = []
    collection_aliases: list[str] = []
    collection_flags: list[int] = []
    unlock_operations: list[tuple[object, ...]] = []
    failure: Exception | None = None
    locked = False
    unlock_cancelled = False
    unlock_report_count: int | None = None
    unlock_attempts = 0
    disconnects = 0
    stale_search_failures = 0
    stale_search_schema: object | None = None
    include_stale_item = False
    stale_schema: object | None = None
    saved_schema: object | None = None
    discard_store = False
    store_requires_disconnect = False
    pending_store: tuple[tuple[str, str], str, object] | None = None
    path_passwords: dict[str, str] = {}
    hide_items_while_locked = False
    default_collection_missing = False

    @classmethod
    def reset(cls) -> None:
        cls.saved = {}
        cls.operations = []
        cls.service_flags = []
        cls.search_flags = []
        cls.search_schemas = []
        cls.store_schemas = []
        cls.clear_schemas = []
        cls.collection_aliases = []
        cls.collection_flags = []
        cls.unlock_operations = []
        cls.failure = None
        cls.locked = False
        cls.unlock_cancelled = False
        cls.unlock_report_count = None
        cls.unlock_attempts = 0
        cls.disconnects = 0
        cls.stale_search_failures = 0
        cls.stale_search_schema = None
        cls.include_stale_item = False
        cls.stale_schema = None
        cls.saved_schema = None
        cls.discard_store = False
        cls.store_requires_disconnect = False
        cls.pending_store = None
        cls.path_passwords = {}
        cls.hide_items_while_locked = False
        cls.default_collection_missing = False

    @classmethod
    def password_store_sync(
        cls, _schema, attributes, _collection, _label, password, _cancellable
    ):
        cls.operations.append(("store", attributes))
        cls.store_schemas.append(_schema)
        if cls.failure:
            raise cls.failure
        if not cls.discard_store:
            key = (attributes["server"], attributes["username"])
            if cls.store_requires_disconnect:
                cls.pending_store = (key, password, _schema)
            else:
                cls.saved[key] = password
            cls.saved_schema = _schema[0]
        return True

    @classmethod
    def password_clear_sync(cls, _schema, attributes, _cancellable):
        cls.operations.append(("clear", attributes))
        cls.clear_schemas.append(_schema)
        if cls.failure:
            raise cls.failure
        return cls.saved.pop(
            (attributes["server"], attributes["username"]), None
        ) is not None


class FakeGLib:
    Error = FakeSecretError
    SOURCE_REMOVE = False
    Variant = FakeVariant
    VariantType = FakeVariantType

    @staticmethod
    def idle_add(callback):
        callback()
        return 1


def load_credentials_module():
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_args: None
    fake_repository = types.ModuleType("gi.repository")
    fake_repository.GLib = FakeGLib
    fake_repository.Gio = FakeGio
    fake_repository.Secret = FakeSecret
    module_path = (
        Path(__file__).parents[2]
        / "src"
        / "pynextcloud_sync"
        / "nextcloud"
        / "credentials.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pynextcloud_sync_credentials_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"gi": fake_gi, "gi.repository": fake_repository},
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class CredentialStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.credentials = load_credentials_module()

    def setUp(self) -> None:
        FakeSecret.reset()

    def test_store_lookup_and_clear_use_compatible_sync_api(self) -> None:
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        stored = []
        looked_up = []
        cleared = []

        store.store(
            "https://cloud.example",
            "alice",
            "app-password",
            lambda ok, error: stored.append((ok, error)),
        )
        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: looked_up.append((password, error)),
        )
        store.clear(
            "https://cloud.example",
            "alice",
            lambda ok, error: cleared.append((ok, error)),
        )

        self.assertEqual(stored, [(True, None)])
        self.assertEqual(looked_up, [("app-password", None)])
        self.assertEqual(cleared, [(True, None)])
        self.assertEqual(
            [name for name, _attributes in FakeSecret.operations],
            ["store", "search", "search", "clear", "clear"],
        )
        self.assertEqual(FakeSecret.store_schemas, [self.credentials.SCHEMA])
        self.assertEqual(FakeSecret.disconnects, 1)
        self.assertEqual(
            FakeSecret.clear_schemas,
            [self.credentials.SCHEMA, self.credentials.LEGACY_SCHEMA],
        )
        self.assertEqual(
            FakeSecret.service_flags,
            [
                FakeSecret.ServiceFlags.OPEN_SESSION,
                FakeSecret.ServiceFlags.OPEN_SESSION,
            ],
        )
        self.assertEqual(FakeSecret.search_flags, [])
        self.assertEqual(
            FakeSecret.search_schemas,
            [self.credentials.SCHEMA_NAME, self.credentials.SCHEMA_NAME],
        )
        self.assertEqual(
            FakeSecret.collection_aliases,
            [FakeSecret.COLLECTION_DEFAULT, FakeSecret.COLLECTION_DEFAULT],
        )

    def test_keyring_cancellation_is_reported_without_escaping(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.locked = True
        FakeSecret.unlock_cancelled = True
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertIsNone(result[0][0])
        self.assertIsInstance(result[0][1], self.credentials.KeyringLockedError)
        self.assertEqual(FakeSecret.unlock_attempts, 1)

    def test_store_success_is_rejected_when_credential_cannot_be_read_back(self) -> None:
        FakeSecret.discard_store = True
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.store(
            "https://cloud.example",
            "alice",
            "app-password",
            lambda ok, error: result.append((ok, error)),
        )

        self.assertFalse(result[0][0])
        self.assertIsInstance(result[0][1], RuntimeError)
        self.assertIn("could not be verified", str(result[0][1]))

    def test_store_verification_uses_a_fresh_secret_service_proxy(self) -> None:
        FakeSecret.store_requires_disconnect = True
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.store(
            "https://cloud.example",
            "alice",
            "app-password",
            lambda ok, error: result.append((ok, error)),
        )

        self.assertEqual(result, [(True, None)])
        self.assertEqual(FakeSecret.disconnects, 1)
        self.assertIsNone(FakeSecret.pending_store)

    def test_locked_keyring_is_unlocked_and_secret_is_loaded(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.locked = True
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [("app-password", None)])
        self.assertFalse(FakeSecret.locked)
        self.assertEqual(FakeSecret.unlock_attempts, 1)

    def test_successful_access_wins_over_stale_zero_unlock_result(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.locked = True
        FakeSecret.unlock_report_count = 0
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [("app-password", None)])
        self.assertFalse(FakeSecret.locked)
        self.assertEqual(FakeSecret.unlock_attempts, 1)

    def test_stale_secret_item_path_reconnects_and_retries_once(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.stale_search_failures = 1
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [("app-password", None)])
        self.assertEqual(FakeSecret.disconnects, 1)
        self.assertEqual(len(FakeSecret.service_flags), 2)
        self.assertEqual(
            [name for name, _attributes in FakeSecret.operations],
            ["search", "search"],
        )

    def test_persistent_stale_secret_item_path_retries_only_once(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.stale_search_failures = 2
        FakeSecret.stale_search_schema = self.credentials.SCHEMA_NAME
        FakeSecret.saved_schema = self.credentials.SCHEMA_NAME
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertIsNone(result[0][0])
        self.assertIsNone(result[0][1])
        self.assertEqual(FakeSecret.disconnects, 1)
        self.assertEqual(len(FakeSecret.service_flags), 3)

    def test_stale_item_does_not_hide_a_newer_valid_credential(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.include_stale_item = True
        FakeSecret.stale_schema = self.credentials.LEGACY_SCHEMA_NAME
        FakeSecret.saved_schema = self.credentials.LEGACY_SCHEMA_NAME
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [("app-password", None)])
        self.assertEqual(FakeSecret.disconnects, 0)

    def test_only_stale_items_become_missing_credentials_after_one_retry(self) -> None:
        FakeSecret.include_stale_item = True
        FakeSecret.stale_schema = self.credentials.LEGACY_SCHEMA_NAME
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [(None, None)])
        self.assertEqual(FakeSecret.disconnects, 1)
        self.assertEqual(len(FakeSecret.service_flags), 3)

    def test_explicit_collection_unlock_precedes_search_hidden_by_locked_keyring(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        FakeSecret.locked = True
        FakeSecret.hide_items_while_locked = True
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [("app-password", None)])
        self.assertFalse(FakeSecret.locked)
        self.assertEqual(FakeSecret.unlock_attempts, 1)
        self.assertEqual(len(FakeSecret.unlock_operations), 1)
        self.assertEqual(
            [name for name, _attributes in FakeSecret.operations],
            ["search"],
        )

    def test_missing_item_is_not_mislabeled_as_a_locked_keyring(self) -> None:
        store = self.credentials.CredentialStore(worker_dispatch=lambda job: job())
        result = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: result.append((password, error)),
        )

        self.assertEqual(result, [(None, None)])

    def test_unlock_result_supports_typelib_return_shapes(self) -> None:
        self.assertEqual(self.credentials.CredentialStore._unlock_count(1), 1)
        self.assertEqual(
            self.credentials.CredentialStore._unlock_count((1, [object()])), 1
        )
        self.assertEqual(self.credentials.CredentialStore._unlock_count((0, [])), 0)
        self.assertEqual(
            self.credentials.CredentialStore._unlock_count([object()]), 1
        )
        self.assertEqual(
            self.credentials.CredentialStore._unlock_count(([object()],)), 1
        )

    def test_simultaneous_lookups_are_coalesced(self) -> None:
        FakeSecret.saved[("https://cloud.example", "alice")] = "app-password"
        jobs = []
        store = self.credentials.CredentialStore(worker_dispatch=jobs.append)
        results = []

        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: results.append(("first", password, error)),
        )
        store.lookup(
            "https://cloud.example",
            "alice",
            lambda password, error: results.append(("second", password, error)),
        )

        self.assertEqual(len(jobs), 1)
        jobs[0]()
        self.assertEqual(
            results,
            [
                ("first", "app-password", None),
                ("second", "app-password", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
