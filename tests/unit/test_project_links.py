from __future__ import annotations

import unittest
from pathlib import Path


class ProjectLinkTests(unittest.TestCase):
    def test_about_links_use_public_website_and_canonical_repository(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        about_source = (project_root / "src/pynextcloud_sync/ui/about.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('WEBSITE_URL = "https://eduhcommerce.com.br"', about_source)
        self.assertIn(
            'PROJECT_URL = "https://github.com/ehstbr/PyNextCloud-Sync"',
            about_source,
        )
        self.assertIn('ISSUES_URL = f"{PROJECT_URL}/issues"', about_source)
        self.assertIn(
            'CHANGELOG_URL = f"{PROJECT_URL}/blob/main/CHANGELOG.md"',
            about_source,
        )

        former_repository = "https://github.com/" + "EduhCommerce/PyNextCloud-Sync"
        text_suffixes = {
            ".desktop",
            ".in",
            ".md",
            ".po",
            ".pot",
            ".py",
            ".sh",
            ".toml",
            ".xml",
        }
        for source_path in project_root.rglob("*"):
            if {"build", "dist"}.intersection(source_path.relative_to(project_root).parts):
                continue
            if not source_path.is_file() or (
                source_path.suffix not in text_suffixes
                and source_path.name not in {"LICENSE"}
            ):
                continue
            self.assertNotIn(
                former_repository,
                source_path.read_text(encoding="utf-8"),
                source_path.relative_to(project_root),
            )

    def test_packaging_metadata_uses_the_public_website(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        expected = "https://eduhcommerce.com.br"

        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        binary_control = (
            project_root / "packaging/debian/binary-control.in"
        ).read_text(encoding="utf-8")
        metainfo = (
            project_root / "data/com.eduhcommerce.PyNextCloudSync.metainfo.xml"
        ).read_text(encoding="utf-8")

        self.assertIn(f'Homepage = "{expected}"', pyproject)
        self.assertIn(f"Homepage: {expected}", binary_control)
        self.assertIn(f'<url type="homepage">{expected}</url>', metainfo)


if __name__ == "__main__":
    unittest.main()
