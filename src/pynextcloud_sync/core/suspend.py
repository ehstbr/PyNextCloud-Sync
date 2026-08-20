from __future__ import annotations

from typing import Callable

from gi.repository import Gio, GLib


class SuspendWatcher:
    def __init__(self, on_resume: Callable[[], None], logger: object) -> None:
        self.on_resume = on_resume
        self.logger = logger
        self.connection: Gio.DBusConnection | None = None
        self.subscription_id = 0

    def start(self) -> None:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.subscription_id = self.connection.signal_subscribe(
                "org.freedesktop.login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
                "/org/freedesktop/login1",
                None,
                Gio.DBusSignalFlags.NONE,
                self._signal,
            )
        except GLib.Error as exc:
            self.logger.warning("Suspend monitoring is unavailable: %s", exc)

    def _signal(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        _signal: str,
        parameters: GLib.Variant,
    ) -> None:
        sleeping = bool(parameters.unpack()[0])
        if not sleeping:
            GLib.timeout_add_seconds(3, self._resume_later)

    def _resume_later(self) -> bool:
        self.on_resume()
        return GLib.SOURCE_REMOVE

    def stop(self) -> None:
        if self.connection and self.subscription_id:
            self.connection.signal_unsubscribe(self.subscription_id)
        self.connection = None
        self.subscription_id = 0
