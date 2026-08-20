from __future__ import annotations

from typing import Callable

from gi.repository import GLib

from .triggers import Trigger


class SyncTimers:
    def __init__(self, request_sync: Callable[[Trigger], None]) -> None:
        self.request_sync = request_sync
        self.local_source = 0
        self.remote_source = 0

    def configure(self, sync: dict) -> None:
        self.stop()
        if sync.get("local_interval_enabled", False):
            seconds = max(1, int(sync.get("local_interval_minutes", 5))) * 60
            self.local_source = GLib.timeout_add_seconds(seconds, self._local)
        if sync.get("remote_interval_enabled", True):
            seconds = max(1, int(sync.get("remote_interval_minutes", 10))) * 60
            self.remote_source = GLib.timeout_add_seconds(seconds, self._remote)

    def stop(self) -> None:
        for source in (self.local_source, self.remote_source):
            if source:
                GLib.source_remove(source)
        self.local_source = self.remote_source = 0

    def _local(self) -> bool:
        self.request_sync(Trigger.LOCAL_INTERVAL)
        return GLib.SOURCE_CONTINUE

    def _remote(self) -> bool:
        self.request_sync(Trigger.REMOTE_INTERVAL)
        return GLib.SOURCE_CONTINUE
