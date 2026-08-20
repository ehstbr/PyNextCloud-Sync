from __future__ import annotations

from typing import Callable

from gi.repository import Gio


class NetworkWatcher:
    def __init__(self, callback: Callable[[bool], None]) -> None:
        self.monitor = Gio.NetworkMonitor.get_default()
        self.callback = callback
        self.handler_id = 0

    @property
    def available(self) -> bool:
        return bool(self.monitor.get_network_available())

    def start(self) -> None:
        if not self.handler_id:
            self.handler_id = self.monitor.connect(
                "network-changed", lambda _monitor, available: self.callback(bool(available))
            )
        self.callback(self.available)

    def stop(self) -> None:
        if self.handler_id:
            self.monitor.disconnect(self.handler_id)
            self.handler_id = 0
