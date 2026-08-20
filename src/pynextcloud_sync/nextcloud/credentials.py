from __future__ import annotations

from threading import Thread
from typing import Callable

import gi

gi.require_version("Secret", "1")
from gi.repository import Gio, GLib, Secret


LEGACY_SCHEMA_NAME = "com.eduhcommerce.PyNextCloudSync.Account"
SCHEMA_NAME = "com.eduhcommerce.PyNextCloudSync.Account.v2"

LEGACY_SCHEMA = Secret.Schema.new(
    LEGACY_SCHEMA_NAME,
    Secret.SchemaFlags.NONE,
    {
        "server": Secret.SchemaAttributeType.STRING,
        "username": Secret.SchemaAttributeType.STRING,
    },
)

SCHEMA = Secret.Schema.new(
    SCHEMA_NAME,
    Secret.SchemaFlags.NONE,
    {
        "server": Secret.SchemaAttributeType.STRING,
        "username": Secret.SchemaAttributeType.STRING,
    },
)


class KeyringLockedError(RuntimeError):
    pass


class CredentialStore:
    def __init__(
        self,
        worker_dispatch: Callable[[Callable[[], None]], None] | None = None,
        logger: object | None = None,
    ) -> None:
        self._pending_lookups: dict[
            tuple[str, str], list[Callable[[str | None, Exception | None], None]]
        ] = {}
        self._worker_dispatch = worker_dispatch or self._start_worker
        self._logger = logger

    @staticmethod
    def _start_worker(operation: Callable[[], None]) -> None:
        Thread(
            target=operation,
            name="pynextcloud-keyring",
            daemon=True,
        ).start()

    @staticmethod
    def _on_main_thread(callback: Callable[[], None]) -> None:
        def deliver() -> bool:
            callback()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(deliver)

    def _attributes(self, server: str, username: str) -> dict[str, str]:
        return {"server": server, "username": username}

    def store(
        self,
        server: str,
        username: str,
        password: str,
        callback: Callable[[bool, Exception | None], None],
    ) -> None:
        attributes = self._attributes(server, username)

        def operation() -> None:
            try:
                stored = Secret.password_store_sync(
                    SCHEMA,
                    attributes,
                    Secret.COLLECTION_DEFAULT,
                    f"PyNextCloud Sync — {username}@{server}",
                    password,
                    None,
                )
                if stored:
                    # password_store_sync() uses the process-wide default
                    # Secret Service. Its proxy can briefly retain the
                    # pre-write search view, so verify through a fresh proxy.
                    Secret.Service.disconnect()
                    verified = self._lookup_with_unlock(attributes, SCHEMA_NAME)
                    if verified != password:
                        raise RuntimeError(
                            "The password keyring reported success but the stored credential could not be verified"
                        )
                error = None
            except Exception as exc:
                stored, error = False, self._map_error(exc)
            self._on_main_thread(lambda: callback(bool(stored), error))

        self._worker_dispatch(operation)

    def lookup(
        self,
        server: str,
        username: str,
        callback: Callable[[str | None, Exception | None], None],
    ) -> None:
        attributes = self._attributes(server, username)
        key = (server, username)
        if key in self._pending_lookups:
            self._pending_lookups[key].append(callback)
            return
        self._pending_lookups[key] = [callback]

        def operation() -> None:
            try:
                password = self._lookup_with_unlock(attributes, SCHEMA_NAME)
                if password is None:
                    password = self._lookup_with_unlock(
                        attributes, LEGACY_SCHEMA_NAME
                    )
                error = None
            except KeyringLockedError as exc:
                password, error = None, exc
            except Exception as exc:
                password, error = None, self._map_error(exc)

            def deliver() -> None:
                callbacks = self._pending_lookups.pop(key, [])
                for pending_callback in callbacks:
                    pending_callback(password, error)

            self._on_main_thread(deliver)

        self._worker_dispatch(operation)

    def _lookup_with_unlock(
        self, attributes: dict[str, str], schema_name: str = SCHEMA_NAME
    ) -> str | None:
        for attempt in range(2):
            try:
                return self._lookup_once(attributes, schema_name)
            except Exception as exc:
                if not self._is_stale_item_error(exc):
                    raise
                if attempt != 0:
                    self._log_warning(
                        "Secret Service still returned only stale credential items after reconnecting; authentication is required again."
                    )
                    return None
                self._log_warning(
                    "Secret Service returned a stale item path; reconnecting and retrying the credential lookup once."
                )
                try:
                    Secret.Service.disconnect()
                except Exception as disconnect_error:
                    self._log_warning(
                        f"Could not disconnect the stale Secret Service proxy cleanly: {disconnect_error}"
                    )
        raise RuntimeError("The stored account credential could not be loaded")

    def _lookup_once(
        self, attributes: dict[str, str], schema_name: str
    ) -> str | None:
        service = Secret.Service.get_sync(
            Secret.ServiceFlags.OPEN_SESSION,
            None,
        )
        if service is None:
            raise RuntimeError("The desktop Secret Service is unavailable")

        # A biometric desktop login can leave the default Login collection
        # locked. On GNOME Keyring, searching immediately during autostart may
        # then return no items at all, even with SECRET_SEARCH_UNLOCK. Resolve
        # and unlock the collection itself first so its items become visible to
        # the subsequent attribute search.
        collection = Secret.Collection.for_alias_sync(
            service,
            Secret.COLLECTION_DEFAULT,
            Secret.CollectionFlags.NONE,
            None,
        )
        unlock_count: int | None = None
        if collection is not None and collection.get_locked():
            self._log_info(
                "The default password keyring is locked; requesting the native unlock prompt."
            )
            unlock_result = service.unlock_sync([collection], None)
            unlock_count = self._unlock_count(unlock_result)

            # Do not decide that the prompt failed from collection.get_locked().
            # Secret.Collection is a D-Bus proxy and its cached Locked property
            # can lag behind a successful native prompt. The returned count can
            # also be zero when another concurrent Secret Service request did the
            # actual unlock. Verify the outcome by trying to load the credential.

        exact_attributes = dict(attributes)
        exact_attributes["xdg:schema"] = schema_name
        search_result = service.call_sync(
            "SearchItems",
            GLib.Variant("(a{ss})", (exact_attributes,)),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        unlocked_paths, locked_paths = search_result.unpack()
        paths = list(unlocked_paths) + list(locked_paths)
        if not paths:
            if unlock_count == 0:
                raise KeyringLockedError("The password keyring remains locked")
            self._log_warning(
                "Secret Service returned no matching credential after the default keyring was checked."
            )
            return None

        stale_error: Exception | None = None
        session_path = service.get_session_dbus_path()
        if not session_path:
            raise RuntimeError("The desktop Secret Service session is unavailable")
        for path in paths:
            try:
                response = service.call_sync(
                    "GetSecrets",
                    GLib.Variant("(aoo)", ([path], session_path)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                secrets = response.get_child_value(0)
                encoded = secrets.lookup_value(
                    path, GLib.VariantType.new("(oayays)")
                )
            except Exception as exc:
                if self._is_stale_item_error(exc):
                    stale_error = exc
                    continue
                raise
            if encoded is not None:
                secret = service.decode_dbus_secret(encoded)
                password = secret.get_text() if secret is not None else None
                if password is not None:
                    return password

        if unlock_count == 0 or locked_paths:
            raise KeyringLockedError("The password keyring remains locked")
        if stale_error is not None:
            raise stale_error
        raise RuntimeError("The stored account credential could not be loaded")

    @staticmethod
    def _is_stale_item_error(error: Exception) -> bool:
        text = str(error).casefold()
        return "no such secret item" in text or (
            "unknown object" in text and "/org/freedesktop/secrets/" in text
        )

    def _log_info(self, message: str) -> None:
        if self._logger is not None:
            self._logger.info(message)

    def _log_warning(self, message: str) -> None:
        if self._logger is not None:
            self._logger.warning(message)

    @staticmethod
    def _unlock_count(result: object) -> int:
        # PyGObject exposes the C return value either directly or as the first
        # element of a tuple followed by the out-parameter list, depending on
        # the typelib version.
        if isinstance(result, list):
            return len(result)
        value = result[0] if isinstance(result, tuple) and result else result
        if isinstance(value, list):
            return len(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def clear(
        self,
        server: str,
        username: str,
        callback: Callable[[bool, Exception | None], None] | None = None,
    ) -> None:
        attributes = self._attributes(server, username)

        def operation() -> None:
            try:
                cleared_current = Secret.password_clear_sync(SCHEMA, attributes, None)
                cleared_legacy = Secret.password_clear_sync(
                    LEGACY_SCHEMA, attributes, None
                )
                cleared = bool(cleared_current or cleared_legacy)
                error = None
            except Exception as exc:
                cleared, error = False, self._map_error(exc)
            if callback:
                self._on_main_thread(lambda: callback(bool(cleared), error))

        self._worker_dispatch(operation)

    @staticmethod
    def _map_error(error: Exception) -> Exception:
        text = str(error).lower()
        if "locked" in text or "cancel" in text or "dismiss" in text:
            return KeyringLockedError(str(error))
        return RuntimeError(str(error))
