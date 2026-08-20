from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class AppState(str, Enum):
    UNCONFIGURED = "unconfigured"
    IDLE_OK = "idle_ok"
    IDLE_MANUAL_ONLY = "idle_manual_only"
    SYNC_QUEUED = "sync_queued"
    SYNCING = "syncing"
    PAUSED_USER = "paused_user"
    PAUSED_BATTERY = "paused_battery"
    OFFLINE = "offline"
    ERROR = "error"
    AUTH_REQUIRED = "auth_required"
    KEYRING_LOCKED = "keyring_locked"
    SAFETY_REVIEW = "safety_review"


class PushState(str, Enum):
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    AUTH_REQUIRED = "authentication_required"


@dataclass(frozen=True)
class StateSnapshot:
    state: AppState
    message: str = ""


class StateController:
    def __init__(self, initial: AppState = AppState.UNCONFIGURED) -> None:
        self._snapshot = StateSnapshot(initial)
        self._listeners: list[Callable[[StateSnapshot], None]] = []

    @property
    def snapshot(self) -> StateSnapshot:
        return self._snapshot

    def subscribe(self, callback: Callable[[StateSnapshot], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        callback(self._snapshot)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def set(self, state: AppState, message: str = "") -> None:
        updated = StateSnapshot(state, message)
        if updated == self._snapshot:
            return
        self._snapshot = updated
        for listener in tuple(self._listeners):
            listener(updated)
