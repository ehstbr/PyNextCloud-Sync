from __future__ import annotations

import unittest
from pathlib import Path

from pynextcloud_sync.ui.activity import parse_activity_line


class ActivityTests(unittest.TestCase):
    def test_parses_level_without_exposing_prefix_in_message(self) -> None:
        entry = parse_activity_line(
            "2026-08-07 14:12:41 INFO    Synchronization completed successfully."
        )
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.message, "Synchronization completed successfully.")
        self.assertEqual(entry.icon_name, "emblem-ok-symbolic")

    def test_preserves_literal_ampersand_from_nextcloudcmd(self) -> None:
        entry = parse_activity_line(
            "2026-08-07 14:12:41 INFO    CMD lambda(const QJsonDocument&)"
        )
        self.assertIn("QJsonDocument&", entry.message)

    def test_warning_has_warning_icon(self) -> None:
        entry = parse_activity_line("2026-08-07 14:12:41 WARNING Push unavailable")
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.icon_name, "dialog-warning-symbolic")

    def test_main_window_supports_expand_collapse_and_context_copy(self) -> None:
        source = (
            Path(__file__).parents[2]
            / "src"
            / "pynextcloud_sync"
            / "ui"
            / "main_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn('primary_click.set_button(Gdk.BUTTON_PRIMARY)', source)
        self.assertIn('secondary_click.set_button(Gdk.BUTTON_SECONDARY)', source)
        self.assertIn('label.set_lines(-1 if expanded else 1)', source)
        self.assertIn('_("Copy Message")', source)
        self.assertIn('self.get_clipboard().set(message)', source)


if __name__ == "__main__":
    unittest.main()
