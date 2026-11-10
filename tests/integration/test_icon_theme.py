from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path


FALLBACK_ROOT = Path(__file__).parents[2] / "data" / "icons" / "fallback"
THEME_INDEX = """[Icon Theme]
Name={name}
Comment=Minimal icon theme for tests
Directories=scalable/apps

[scalable/apps]
Size=48
Type=Scalable
MinSize=8
MaxSize=256
Context=Applications
"""


class IconThemeTests(unittest.TestCase):
    def test_fallback_icons_resolve_with_a_scalable_only_hicolor_index(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK 4 is unavailable")

        icons = {
            path.stem: path
            for path in FALLBACK_ROOT.glob("hicolor/*/apps/*-symbolic.svg")
        }
        required = {
            "avatar-default-symbolic",
            "document-open-recent-symbolic",
            "emblem-ok-symbolic",
            "emblem-synchronizing-symbolic",
            "emblem-system-symbolic",
            "folder-symbolic",
        }
        self.assertLessEqual(required, icons.keys())
        with tempfile.TemporaryDirectory() as directory:
            search_root = Path(directory)
            for name in ("hicolor", "TestTheme"):
                theme_directory = search_root / name
                (theme_directory / "scalable" / "apps").mkdir(parents=True)
                (theme_directory / "index.theme").write_text(
                    THEME_INDEX.format(name=name), encoding="utf-8"
                )
            native_folder = search_root / "TestTheme/scalable/apps/folder-symbolic.svg"
            shutil.copyfile(icons["folder-symbolic"], native_folder)

            theme = Gtk.IconTheme.new()
            theme.set_search_path([str(search_root), str(FALLBACK_ROOT)])
            theme.set_theme_name("TestTheme")

            for name, fallback in icons.items():
                with self.subTest(icon=name):
                    self.assertTrue(theme.has_icon(name))
                    icon = theme.lookup_icon(
                        name, [], 24, 1, Gtk.TextDirection.LTR,
                        Gtk.IconLookupFlags.FORCE_SYMBOLIC,
                    )
                    expected = native_folder if name == "folder-symbolic" else fallback
                    self.assertEqual(icon.get_file().get_path(), str(expected))
                    self.assertTrue(icon.is_symbolic())
