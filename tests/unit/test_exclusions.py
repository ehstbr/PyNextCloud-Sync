from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pynextcloud_sync.core.exclusions import (
    DEFAULT_PATTERNS,
    ExclusionMatcher,
    InvalidPattern,
    validate_pattern,
)


class ExclusionTests(unittest.TestCase):
    def test_matches_known_disposable_files(self) -> None:
        matcher = ExclusionMatcher(DEFAULT_PATTERNS)
        self.assertTrue(matcher.matches_name(".DS_Store"))
        self.assertTrue(matcher.matches_name("document.swp"))
        self.assertFalse(matcher.matches_name(".important-hidden-file"))
        self.assertFalse(matcher.matches_name("notes.tmp"))

    def test_rejects_paths_and_broad_patterns(self) -> None:
        for value in ("folder/file.txt", "folder\\file.txt", "../secret", "*", ".*"):
            with self.subTest(value=value), self.assertRaises(InvalidPattern):
                validate_pattern(value)

    def test_generated_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "excludes.lst"
            ExclusionMatcher(DEFAULT_PATTERNS).write_nextcloudcmd_file(path)
            self.assertIn("Thumbs.db", path.read_text(encoding="utf-8"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

