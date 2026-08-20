from __future__ import annotations

from typing import Callable

from gi.repository import Gio, GLib


class PowerWatcher:
    def __init__(self, callback: Callable[[bool], None], logger: object) -> None:
        self.callback = callback
        self.logger = logger
        self.proxy: Gio.DBusProxy | None = None
        self.handler_id = 0
        self.available = False
        self.on_battery = False

    def start(self) -> None:
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.UPower",
                "/org/freedesktop/UPower",
                "org.freedesktop.UPower",
                None,
            )
            self.handler_id = self.proxy.connect("g-properties-changed", self._changed)
            self.available = True
            self._emit()
        except GLib.Error as exc:
            self.available = False
            self.logger.warning("UPower is unavailable: %s", exc)

    def _changed(self, _proxy: Gio.DBusProxy, changed: GLib.Variant, _invalidated: list[str]) -> None:
        if "OnBattery" in changed.unpack():
            self._emit()

    def _emit(self) -> None:
        if not self.proxy:
            return
        value = self.proxy.get_cached_property("OnBattery")
        self.on_battery = bool(value.unpack()) if value else False
        self.callback(self.on_battery)

    def stop(self) -> None:
        if self.proxy and self.handler_id:
            self.proxy.disconnect(self.handler_id)
        self.proxy = None
        self.handler_id = 0
