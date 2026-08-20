from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from pynextcloud_sync.core.safety import account_fingerprint
from pynextcloud_sync.util.paths import ensure_private_directory, state_dir

RUN_MARKER_FORMAT = 1


class SyncRunMarker:
    """Durable breadcrumb around a nextcloudcmd run.

    The marker does not model synchronization state. It only records that the
    wrapper started nextcloudcmd and has not yet committed a new safety
    baseline. The safety manifest remains the last-known-good source used by
    SafetyGuard.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "sync-run.json")

    def load(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("format") != RUN_MARKER_FORMAT:
            return None
        return payload

    def pending_for(self, account: dict[str, Any]) -> bool:
        if not self.path.exists():
            return False
        payload = self.load()
        if payload is None:
            # An unreadable/corrupt marker is still evidence that a previous
            # wrapper run did not reach a confirmed post-sync baseline.
            return True
        return payload.get("account_fingerprint") == account_fingerprint(account)

    def begin(self, account: dict[str, Any]) -> None:
        ensure_private_directory(self.path.parent)
        payload = {
            "format": RUN_MARKER_FORMAT,
            "account_fingerprint": account_fingerprint(account),
            "started_at_unix": int(time.time()),
        }
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            self._fsync_parent()
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        if not self.path.exists():
            return
        self.path.unlink()
        self._fsync_parent()

    def _fsync_parent(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(self.path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
