from __future__ import annotations

import os
import re
from pathlib import Path


APP_DIR = "pynextcloud-sync"


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_DIR


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_DIR


def autostart_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "autostart"


def gtk_bookmarks_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "gtk-3.0" / "bookmarks"


def user_data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")


def desktop_dir() -> Path:
    """Return the XDG desktop directory without invoking a shell command."""

    override = os.environ.get("XDG_DESKTOP_DIR")
    if override:
        return Path(override).expanduser()

    user_dirs = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "user-dirs.dirs"
    try:
        content = user_dirs.read_text(encoding="utf-8")
    except OSError:
        return Path.home() / "Desktop"

    match = re.search(r'^XDG_DESKTOP_DIR="(.*)"$', content, flags=re.MULTILINE)
    if not match:
        return Path.home() / "Desktop"
    value = match.group(1).replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else Path.home() / "Desktop"


def default_sync_root() -> Path:
    return Path.home() / "NextCloud"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path
