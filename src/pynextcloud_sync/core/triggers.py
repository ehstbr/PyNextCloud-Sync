from __future__ import annotations

from enum import Enum


class Trigger(str, Enum):
    LOCAL_INOTIFY = "LOCAL_INOTIFY"
    LOCAL_INTERVAL = "LOCAL_INTERVAL"
    LOCAL_RECOVERY = "LOCAL_RECOVERY"
    REMOTE_PUSH = "REMOTE_PUSH"
    REMOTE_INTERVAL = "REMOTE_INTERVAL"
    MANUAL = "MANUAL"
    STARTUP = "STARTUP"
    NETWORK_RESTORED = "NETWORK_RESTORED"
    RESUME = "RESUME"
    RETRY = "RETRY"


def manual_only(sync_settings: dict) -> bool:
    return not any(
        (
            sync_settings.get("local_inotify_enabled", False),
            sync_settings.get("local_interval_enabled", False),
            sync_settings.get("remote_push_enabled", False),
            sync_settings.get("remote_interval_enabled", False),
        )
    )


class CoalescingQueue:
    """A path-free, reason-preserving queue for full reconciliations."""

    def __init__(self) -> None:
        self._reasons: set[Trigger] = set()

    def add(self, trigger: Trigger) -> None:
        self._reasons.add(trigger)

    def extend(self, triggers: set[Trigger]) -> None:
        self._reasons.update(triggers)

    def take(self) -> set[Trigger]:
        reasons = set(self._reasons)
        self._reasons.clear()
        return reasons

    def clear(self) -> None:
        self._reasons.clear()

    def discard(self, trigger: Trigger) -> None:
        self._reasons.discard(trigger)

    def __bool__(self) -> bool:
        return bool(self._reasons)

    def __len__(self) -> int:
        return len(self._reasons)
