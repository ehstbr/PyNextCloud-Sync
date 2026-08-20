from __future__ import annotations

import os
import shlex
from pathlib import Path

from pynextcloud_sync import APP_ID
from pynextcloud_sync.util.paths import autostart_dir


class AutostartManager:
    def __init__(self, desktop_path: Path | None = None) -> None:
        self.path = desktop_path or (autostart_dir() / f"{APP_ID}.desktop")

    def _command(self) -> str:
        launcher = os.environ.get("PYNEXTCLOUD_LAUNCHER")
        if launcher:
            return f"{shlex.quote(launcher)} --background"
        return "pynextcloud-sync --background"

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(
            (
                "[Desktop Entry]",
                "Type=Application",
                "Name=PyNextCloud Sync",
                f"Exec={self._command()}",
                f"Icon={APP_ID}",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "StartupNotify=false",
                "",
            )
        )
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)
