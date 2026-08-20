from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pynextcloud_sync.util.paths import (
    desktop_dir,
    gtk_bookmarks_path,
    project_root,
    user_data_dir,
)


FOLDER_ICON_NAME = "com.eduhcommerce.PyNextCloudSync-folder"
FOLDER_ICON_FILENAME = f"{FOLDER_ICON_NAME}.svg"
CUSTOM_ICON_ATTRIBUTE = "metadata::custom-icon-name"


@dataclass(frozen=True)
class IntegrationState:
    nautilus_bookmark: bool
    desktop_shortcut: bool
    special_icon: bool


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _bookmark_path(line: str) -> Path | None:
    uri = line.strip().split(" ", 1)[0]
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return None
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path))


class DesktopIntegration:
    """Own the small, reversible GNOME integrations for one sync root."""

    def __init__(
        self,
        sync_root: Path,
        *,
        bookmarks: Path | None = None,
        desktop: Path | None = None,
        icon_source: Path | None = None,
        metadata_getter: Callable[[Path, bool], str | None] | None = None,
        metadata_setter: Callable[[Path, str | None, bool], bool] | None = None,
    ) -> None:
        self.sync_root = sync_root.expanduser().absolute()
        self.bookmarks = bookmarks or gtk_bookmarks_path()
        self.desktop = desktop or desktop_dir()
        self.icon_source = icon_source or (
            project_root() / "data" / "icons" / FOLDER_ICON_FILENAME
        )
        self._metadata_getter = metadata_getter or self._get_custom_icon
        self._metadata_setter = metadata_setter or self._set_custom_icon
        self._listeners: list[Callable[[IntegrationState], None]] = []
        self._monitors: list[object] = []

    @property
    def desktop_names(self) -> tuple[str, str]:
        name = self.sync_root.name or "NextCloud"
        return name, f"{name} (PyNextCloud Sync)"

    @property
    def desktop_candidates(self) -> tuple[Path, Path]:
        primary, fallback = self.desktop_names
        return self.desktop / primary, self.desktop / fallback

    @property
    def state(self) -> IntegrationState:
        return IntegrationState(
            nautilus_bookmark=self.has_nautilus_bookmark(),
            desktop_shortcut=self.has_desktop_shortcut(),
            special_icon=self.has_special_icon(),
        )

    def initialize_defaults(self) -> dict[str, bool]:
        results = {
            "nautilus_bookmark": self.set_nautilus_bookmark(True),
            "desktop_shortcut": self.set_desktop_shortcut(True),
        }
        results["special_icon"] = self.set_special_icon(True)
        return results

    def cleanup(self) -> None:
        self.set_nautilus_bookmark(False)
        self.set_special_icon(False)
        self.set_desktop_shortcut(False)

    def _bookmark_lines(self) -> list[str]:
        try:
            return self.bookmarks.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError:
            return []

    def has_nautilus_bookmark(self) -> bool:
        return any(
            path is not None and _same_path(path, self.sync_root)
            for path in map(_bookmark_path, self._bookmark_lines())
        )

    def set_nautilus_bookmark(self, enabled: bool) -> bool:
        lines = self._bookmark_lines()
        matching = [
            path is not None and _same_path(path, self.sync_root)
            for path in map(_bookmark_path, lines)
        ]
        if enabled:
            if any(matching):
                return True
            lines.append(f"{self.sync_root.as_uri()} {self.sync_root.name or 'NextCloud'}")
        else:
            if not any(matching):
                return True
            lines = [line for line, is_match in zip(lines, matching) if not is_match]
        try:
            self._write_bookmarks(lines)
        except OSError:
            return False
        self._notify()
        return self.has_nautilus_bookmark() == enabled

    def _write_bookmarks(self, lines: list[str]) -> None:
        self.bookmarks.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.bookmarks.with_name(f".{self.bookmarks.name}.pynextcloud-sync.tmp")
        payload = "\n".join(lines)
        if payload:
            payload += "\n"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.bookmarks)
        finally:
            temporary.unlink(missing_ok=True)

    def _matching_desktop_shortcuts(self) -> list[Path]:
        matches: list[Path] = []
        for candidate in self.desktop_candidates:
            if not candidate.is_symlink():
                continue
            try:
                target = candidate.readlink()
            except OSError:
                continue
            if not target.is_absolute():
                target = candidate.parent / target
            if _same_path(target, self.sync_root):
                matches.append(candidate)
        return matches

    def has_desktop_shortcut(self) -> bool:
        return bool(self._matching_desktop_shortcuts())

    def set_desktop_shortcut(self, enabled: bool) -> bool:
        matches = self._matching_desktop_shortcuts()
        if enabled:
            if matches:
                return True
            try:
                self.desktop.mkdir(parents=True, exist_ok=True)
                target = next(
                    (path for path in self.desktop_candidates if not os.path.lexists(path)),
                    None,
                )
                if target is None:
                    return False
                target.symlink_to(self.sync_root, target_is_directory=True)
                if self.has_special_icon():
                    self._metadata_setter(target, FOLDER_ICON_NAME, True)
            except OSError:
                return False
        else:
            for path in matches:
                try:
                    self._metadata_setter(path, None, True)
                    path.unlink()
                except OSError:
                    return False
        self._notify()
        return self.has_desktop_shortcut() == enabled

    def _ensure_icon_available(self) -> bool:
        system_icon = Path("/usr/share/icons/hicolor/scalable/places") / FOLDER_ICON_FILENAME
        if system_icon.is_file():
            return True
        if not self.icon_source.is_file():
            return False
        destination = (
            user_data_dir() / "icons" / "hicolor" / "scalable" / "places" / FOLDER_ICON_FILENAME
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (
                not destination.exists()
                or destination.read_bytes() != self.icon_source.read_bytes()
            ):
                temporary = destination.with_suffix(".tmp")
                shutil.copyfile(self.icon_source, temporary)
                temporary.chmod(0o644)
                temporary.replace(destination)
            return True
        except OSError:
            return False

    def has_special_icon(self) -> bool:
        return self._metadata_getter(self.sync_root, False) == FOLDER_ICON_NAME

    def set_special_icon(self, enabled: bool) -> bool:
        if enabled and not self._ensure_icon_available():
            return False
        value = FOLDER_ICON_NAME if enabled else None
        if not self._metadata_setter(self.sync_root, value, False):
            return False
        for shortcut in self._matching_desktop_shortcuts():
            self._metadata_setter(shortcut, value, True)
        self._notify()
        return self.has_special_icon() == enabled

    @staticmethod
    def _get_custom_icon(path: Path, nofollow: bool) -> str | None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            flags = (
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
                if nofollow
                else Gio.FileQueryInfoFlags.NONE
            )
            info = Gio.File.new_for_path(str(path)).query_info(
                CUSTOM_ICON_ATTRIBUTE, flags, None
            )
            return info.get_attribute_string(CUSTOM_ICON_ATTRIBUTE)
        except Exception:
            return None

    @staticmethod
    def _set_custom_icon(path: Path, value: str | None, nofollow: bool) -> bool:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            flags = (
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
                if nofollow
                else Gio.FileQueryInfoFlags.NONE
            )
            file = Gio.File.new_for_path(str(path))
            if value is None:
                return bool(
                    file.set_attribute(
                        CUSTOM_ICON_ATTRIBUTE,
                        Gio.FileAttributeType.INVALID,
                        None,
                        flags,
                        None,
                    )
                )
            return bool(file.set_attribute_string(CUSTOM_ICON_ATTRIBUTE, value, flags, None))
        except Exception:
            return False

    def subscribe(
        self, callback: Callable[[IntegrationState], None]
    ) -> Callable[[], None]:
        self._listeners.append(callback)
        if len(self._listeners) == 1:
            self._start_monitors()

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
            if not self._listeners:
                self._stop_monitors()

        return unsubscribe

    def _start_monitors(self) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            for path, is_directory in (
                (self.bookmarks.parent, True),
                (self.desktop, True),
            ):
                if not path.exists():
                    continue
                file = Gio.File.new_for_path(str(path))
                monitor = (
                    file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
                    if is_directory
                    else file.monitor_file(Gio.FileMonitorFlags.NONE, None)
                )
                monitor.connect("changed", lambda *_args: self._notify())
                self._monitors.append(monitor)
        except Exception:
            self._stop_monitors()

    def _stop_monitors(self) -> None:
        for monitor in self._monitors:
            try:
                monitor.cancel()
            except Exception:
                pass
        self._monitors.clear()

    def _notify(self) -> None:
        state = self.state
        for listener in tuple(self._listeners):
            listener(state)

    def close(self) -> None:
        self._listeners.clear()
        self._stop_monitors()
