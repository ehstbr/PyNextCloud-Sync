from __future__ import annotations

import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NextcloudCmdMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    environment: dict[str, str]


def find_nextcloudcmd() -> str | None:
    return shutil.which("nextcloudcmd")


def build_command(
    account: dict[str, Any],
    sync: dict[str, Any],
    network: dict[str, Any],
    password: str,
    exclude_file: Path | None = None,
    executable: str | None = None,
) -> CommandSpec:
    binary = executable or find_nextcloudcmd()
    if not binary:
        raise NextcloudCmdMissingError(
            "nextcloudcmd is not installed (Ubuntu package: nextcloud-desktop-cmd)."
        )
    argv = [
        binary,
        "--non-interactive",
        "--max-sync-retries",
        str(int(sync.get("max_sync_retries", 3))),
        "-h",
    ]
    if not sync.get("detailed_output", True):
        argv.append("--silent")
    if network.get("trust_invalid_certificates", False):
        argv.append("--trust")
    proxy = network.get("custom_proxy")
    if proxy:
        argv.extend(("--httpproxy", str(proxy)))
    if exclude_file:
        argv.extend(("--exclude", str(exclude_file)))
    argv.extend((str(account["local_root"]), str(account["server_url"])))
    environment = {"NC_USER": str(account["login_name"]), "NC_PASSWORD": password}
    return CommandSpec(tuple(argv), environment)


AUTH_ERROR_MARKERS = (
    "authentication failed",
    "invalid credentials",
    "access forbidden",
    "unauthorized",
    "http error code 401",
    "server replied: unauthorized",
)


CONFLICT_MARKERS = ("conflict", "conflicted copy", "csync_exclude_conflict")


class BoundedOutputCapture:
    """Classify a command stream while retaining only a small diagnostic tail."""

    def __init__(self, max_lines: int = 200) -> None:
        if max_lines < 1:
            raise ValueError("max_lines must be positive")
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._authentication_seen = False
        self._conflict_seen = False

    def feed(self, text: str) -> None:
        self._lines.append(text)
        lowered = text.lower()
        self._authentication_seen |= any(
            marker in lowered for marker in AUTH_ERROR_MARKERS
        )
        self._conflict_seen |= any(marker in lowered for marker in CONFLICT_MARKERS)

    @property
    def output(self) -> str:
        return "\n".join(self._lines)

    def classification(self, exit_code: int) -> str:
        if self._authentication_seen:
            return "authentication"
        if exit_code == 0 and self._conflict_seen:
            return "conflict"
        return "success" if exit_code == 0 else "sync_error"


def classify_output(output: str, exit_code: int) -> str:
    capture = BoundedOutputCapture(max_lines=1)
    capture.feed(output)
    return capture.classification(exit_code)
