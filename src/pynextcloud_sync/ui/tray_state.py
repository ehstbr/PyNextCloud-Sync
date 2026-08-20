from __future__ import annotations

from dataclasses import dataclass

from pynextcloud_sync.core.state import AppState


@dataclass(frozen=True)
class TrayPresentation:
    icon_key: str
    status: str
    label: str
    user_paused: bool = False


STATE_PRESENTATIONS: dict[AppState, TrayPresentation] = {
    AppState.UNCONFIGURED: TrayPresentation(
        "offline", "NeedsAttention", "Not Configured"
    ),
    AppState.IDLE_OK: TrayPresentation("ok", "Active", "Synchronized"),
    AppState.IDLE_MANUAL_ONLY: TrayPresentation(
        "paused", "Active", "Automatic Sync Is Off"
    ),
    AppState.SYNC_QUEUED: TrayPresentation(
        "syncing", "Active", "Synchronization Scheduled"
    ),
    AppState.SYNCING: TrayPresentation("syncing", "Active", "Synchronizing…"),
    AppState.PAUSED_USER: TrayPresentation(
        "paused", "Active", "Paused", user_paused=True
    ),
    AppState.PAUSED_BATTERY: TrayPresentation(
        "battery", "Active", "Paused on Battery"
    ),
    AppState.OFFLINE: TrayPresentation("offline", "Active", "Offline"),
    AppState.ERROR: TrayPresentation(
        "error", "NeedsAttention", "Synchronization Error"
    ),
    AppState.AUTH_REQUIRED: TrayPresentation(
        "error", "NeedsAttention", "Account Needs Attention"
    ),
    AppState.KEYRING_LOCKED: TrayPresentation(
        "error", "NeedsAttention", "Password Keyring Locked"
    ),
    AppState.SAFETY_REVIEW: TrayPresentation(
        "error", "NeedsAttention", "Safety Review Required"
    ),
}


def presentation_for(state: AppState) -> TrayPresentation:
    """Return the complete tray presentation for an application state."""

    return STATE_PRESENTATIONS[state]
