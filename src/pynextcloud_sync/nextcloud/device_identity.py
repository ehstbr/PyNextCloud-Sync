from __future__ import annotations

import re
import socket


MAX_DEVICE_NAME_LENGTH = 48


def normalized_device_name(value: str | None = None) -> str:
    """Return a short ASCII device name suitable for an HTTP User-Agent."""
    candidate = value if value is not None else socket.gethostname()
    candidate = candidate.strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate)
    candidate = re.sub(r"[-_.]{2,}", "-", candidate).strip("-_.")
    return candidate[:MAX_DEVICE_NAME_LENGTH] or "Linux-device"


def authorization_name(device_name: str | None = None) -> str:
    """Stable name shown for new Login Flow authorizations in Nextcloud."""
    return f"PyNextCloud-Sync ({normalized_device_name(device_name)})"
