from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pynextcloud_sync.core.desktop_integration import (
    FOLDER_ICON_NAME,
    DesktopIntegration,
)


class FakeMetadata:
    def __init__(self) -> None:
        self.values: dict[tuple[Path, bool], str] = {}

    def get(self, path: Path, nofollow: bool) -> str | None:
        return self.values.get((path, nofollow))

    def set(self, path: Path, value: str | None, nofollow: bool) -> bool:
        key = (path, nofollow)
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value
        return True


class DesktopIntegrationTests(unittest.TestCase):
    def _integration(
        self, directory: str
    ) -> tuple[DesktopIntegration, Path, Path, Path, FakeMetadata]:
        base = Path(directory)
        root = base / "Next Cloud"
        root.mkdir()
        desktop = base / "Desktop"
        bookmarks = base / "config" / "gtk-3.0" / "bookmarks"
        icon = base / "folder.svg"
        icon.write_text("<svg/>", encoding="utf-8")
        metadata = FakeMetadata()
        integration = DesktopIntegration(
            root,
            bookmarks=bookmarks,
            desktop=desktop,
            icon_source=icon,
            metadata_getter=metadata.get,
            metadata_setter=metadata.set,
        )
        return integration, root, desktop, bookmarks, metadata

    def test_bookmark_preserves_other_entries_and_tracks_manual_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            integration, root, _desktop, bookmarks, _metadata = self._integration(
                directory
            )
            bookmarks.parent.mkdir(parents=True)
            bookmarks.write_text(
                "file:///tmp/Documents Work files\nsmb://server/share Shared\n",
                encoding="utf-8",
            )

            self.assertTrue(integration.set_nautilus_bookmark(True))
            content = bookmarks.read_text(encoding="utf-8")
            self.assertIn("file:///tmp/Documents Work files", content)
            self.assertIn(root.as_uri(), content)
            self.assertTrue(integration.state.nautilus_bookmark)

            bookmarks.write_text(
                "file:///tmp/Documents Work files\nsmb://server/share Shared\n",
                encoding="utf-8",
            )
            self.assertFalse(integration.state.nautilus_bookmark)

    def test_desktop_shortcut_uses_safe_fallback_and_never_replaces_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            integration, root, desktop, _bookmarks, _metadata = self._integration(
                directory
            )
            desktop.mkdir()
            collision = desktop / root.name
            collision.write_text("keep", encoding="utf-8")

            self.assertTrue(integration.set_desktop_shortcut(True))
            shortcut = desktop / f"{root.name} (PyNextCloud Sync)"
            self.assertTrue(shortcut.is_symlink())
            self.assertEqual(shortcut.resolve(), root)
            self.assertEqual(collision.read_text(encoding="utf-8"), "keep")

            self.assertTrue(integration.set_desktop_shortcut(False))
            self.assertFalse(os.path.lexists(shortcut))
            self.assertTrue(collision.is_file())

    def test_special_icon_applies_to_folder_and_managed_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            integration, root, desktop, _bookmarks, metadata = self._integration(
                directory
            )
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(directory) / "data")}):
                self.assertTrue(integration.set_desktop_shortcut(True))
                self.assertTrue(integration.set_special_icon(True))
                shortcut = desktop / root.name
                self.assertEqual(metadata.get(root, False), FOLDER_ICON_NAME)
                self.assertEqual(metadata.get(shortcut, True), FOLDER_ICON_NAME)
                self.assertTrue(integration.state.special_icon)

                self.assertTrue(integration.set_special_icon(False))
                self.assertIsNone(metadata.get(root, False))
                self.assertIsNone(metadata.get(shortcut, True))

    def test_cleanup_removes_only_integrations_and_keeps_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            integration, root, _desktop, _bookmarks, _metadata = self._integration(
                directory
            )
            local_file = root / "keep.txt"
            local_file.write_text("data", encoding="utf-8")
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(directory) / "data")}):
                results = integration.initialize_defaults()
                self.assertTrue(all(results.values()))
                integration.cleanup()

            self.assertTrue(local_file.is_file())
            self.assertFalse(integration.state.nautilus_bookmark)
            self.assertFalse(integration.state.desktop_shortcut)


if __name__ == "__main__":
    unittest.main()
