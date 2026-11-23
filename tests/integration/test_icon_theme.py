from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[2] / "src" / "pynextcloud_sync"
BUNDLE = SOURCE_ROOT / "icons"
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
    def test_bundled_icons_resolve_with_an_incomplete_desktop_theme(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK 4 is unavailable")

        icons = {
            path.stem: path
            for path in BUNDLE.glob("hicolor/scalable/apps/*-symbolic.svg")
        }
        required = set()
        for source in SOURCE_ROOT.rglob("*.py"):
            required.update(re.findall(
                r'["\'](pynextcloud-sync-[a-z0-9-]+-symbolic)["\']',
                source.read_text(encoding="utf-8"),
            ))
        self.assertIn("pynextcloud-sync-avatar-default-symbolic", required)
        self.assertLessEqual(required, icons.keys())
        with tempfile.TemporaryDirectory() as directory:
            search_root = Path(directory)
            for name in ("hicolor", "TestTheme"):
                theme_directory = search_root / name
                (theme_directory / "scalable" / "apps").mkdir(parents=True)
                (theme_directory / "index.theme").write_text(
                    THEME_INDEX.format(name=name), encoding="utf-8"
                )
            native_avatar = search_root / "TestTheme/scalable/apps/avatar-default-symbolic.svg"
            native_avatar.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>',
                encoding="utf-8",
            )

            theme = Gtk.IconTheme.new()
            theme.set_search_path([str(search_root), str(BUNDLE)])
            theme.set_theme_name("TestTheme")

            for name, bundled in icons.items():
                with self.subTest(icon=name):
                    self.assertTrue(theme.has_icon(name))
                    icon = theme.lookup_icon(
                        name, [], 24, 1, Gtk.TextDirection.LTR,
                        Gtk.IconLookupFlags.FORCE_SYMBOLIC,
                    )
                    self.assertEqual(icon.get_file().get_path(), str(bundled))
                    self.assertTrue(icon.is_symbolic())
