from __future__ import annotations

import re
from dataclasses import dataclass


LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(?P<message>.*)$"
)


LEVEL_ICONS = {
    "DEBUG": "utilities-terminal-symbolic",
    "INFO": "dialog-information-symbolic",
    "WARNING": "dialog-warning-symbolic",
    "ERROR": "dialog-error-symbolic",
    "CRITICAL": "software-update-urgent-symbolic",
}


@dataclass(frozen=True)
class ActivityEntry:
    level: str
    message: str
    icon_name: str


def parse_activity_line(line: str) -> ActivityEntry:
    """Turn one formatted application log line into a compact UI entry."""

    match = LOG_LINE.match(line.strip())
    if match:
        level = match.group("level")
        message = match.group("message").strip()
    else:
        level = "INFO"
        message = line.strip()

    if level == "INFO" and "completed successfully" in message.casefold():
        icon_name = "emblem-ok-symbolic"
    else:
        icon_name = LEVEL_ICONS.get(level, "dialog-information-symbolic")
    return ActivityEntry(level=level, message=message, icon_name=icon_name)
