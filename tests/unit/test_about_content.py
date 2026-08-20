from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from pathlib import Path

from pynextcloud_sync.ui.about_content import release_notes_markup, terms_text


class AboutContentTests(unittest.TestCase):
    def test_release_notes_are_valid_appstream_xml(self) -> None:
        root = ET.fromstring(f"<description>{release_notes_markup()}</description>")
        self.assertGreater(len(root.findall("p")), 0)
        self.assertGreater(len(root.findall("ul")), 0)

    def test_legal_texts_are_complete(self) -> None:
        about_source = (
            Path(__file__).resolve().parents[2]
            / "src/pynextcloud_sync/ui/about.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Gtk.License.GPL_3_0", about_source)
        self.assertNotIn("about.set_license(", about_source)
        self.assertIn("GNU General Public License version 3 or later", terms_text())
        self.assertIn("No telemetry", terms_text())
        self.assertIn("lost, corrupted, deleted", terms_text())
        self.assertIn("future Nextcloud versions is not guaranteed", terms_text())


if __name__ == "__main__":
    unittest.main()
