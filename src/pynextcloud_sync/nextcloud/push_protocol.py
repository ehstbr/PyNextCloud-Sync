from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PushEndpoints:
    websocket: str
    pre_auth: str | None = None


def parse_push_capability(payload: dict[str, Any]) -> PushEndpoints | None:
    capabilities = payload.get("ocs", {}).get("data", {}).get("capabilities", {})
    push = capabilities.get("notify_push")
    if not isinstance(push, dict):
        return None
    endpoints = push.get("endpoints", push)
    websocket = endpoints.get("websocket") if isinstance(endpoints, dict) else None
    pre_auth = endpoints.get("pre_auth") if isinstance(endpoints, dict) else None
    if not isinstance(websocket, str) or not websocket:
        return None
    return PushEndpoints(websocket=websocket, pre_auth=pre_auth if isinstance(pre_auth, str) else None)


def validate_push_transport(server_url: str, websocket_url: str) -> None:
    server_scheme = urlsplit(server_url).scheme.lower()
    websocket_scheme = urlsplit(websocket_url).scheme.lower()
    if websocket_scheme not in {"ws", "wss"}:
        raise ValueError("The server returned an invalid push WebSocket URL.")
    if server_scheme == "https" and websocket_scheme != "wss":
        raise ValueError("Refusing to downgrade secure Nextcloud push to an insecure WebSocket.")

