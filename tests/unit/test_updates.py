from __future__ import annotations

import json
import unittest

from pynextcloud_sync.core.updates import (
    MAX_MANIFEST_BYTES,
    RELEASES_URL,
    VERSION_MANIFEST_URL,
    SemanticVersion,
    UpdateChecker,
    UpdateManifestError,
    evaluate_update,
    parse_update_manifest,
)


def manifest_bytes(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "schema_version": 1,
        "version": "1.2.0",
        "mandatory": False,
        "released_at": "2026-08-09T01:51:24Z",
        "summary": "Corrections and improvements.",
        "changelog": ["Fixed one issue.", "Improved one workflow."],
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class SemanticVersionTests(unittest.TestCase):
    def test_numeric_components_are_not_compared_as_strings(self) -> None:
        self.assertGreater(
            SemanticVersion.parse("1.10.0"),
            SemanticVersion.parse("1.9.9"),
        )

    def test_semver_prerelease_precedence_and_build_metadata(self) -> None:
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        ]
        parsed = [SemanticVersion.parse(value) for value in ordered]
        self.assertEqual(parsed, sorted(parsed))
        self.assertEqual(
            SemanticVersion.parse("1.0.0+build.1"),
            SemanticVersion.parse("1.0.0+build.2"),
        )

    def test_invalid_versions_are_rejected(self) -> None:
        for value in ("1.2", "1.02.3", "1.2.3-", "1.2.3-01", "v1.2.3", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SemanticVersion.parse(value)


class UpdateManifestTests(unittest.TestCase):
    def test_valid_manifest_contains_plain_summary_and_utc_release_date(self) -> None:
        manifest = parse_update_manifest(manifest_bytes(mandatory=True))
        self.assertEqual(manifest.version_text, "1.2.0")
        self.assertTrue(manifest.mandatory)
        self.assertEqual(manifest.summary, "Corrections and improvements.")
        self.assertEqual(
            manifest.changelog,
            ("Fixed one issue.", "Improved one workflow."),
        )
        self.assertEqual(manifest.released_at_utc_text, "2026-08-09 01:51 UTC")

    def test_newer_equal_and_older_versions_are_evaluated_safely(self) -> None:
        self.assertTrue(
            evaluate_update(
                manifest_bytes(version="1.10.0"), current_version="1.9.9"
            ).update_available
        )
        self.assertFalse(
            evaluate_update(
                manifest_bytes(version="1.9.9"), current_version="1.9.9"
            ).update_available
        )
        self.assertFalse(
            evaluate_update(
                manifest_bytes(version="1.8.9"), current_version="1.9.9"
            ).update_available
        )

    def test_invalid_or_incomplete_manifests_are_rejected(self) -> None:
        invalid_values = (
            b"not-json",
            json.dumps([]).encode(),
            manifest_bytes(schema_version=2),
            manifest_bytes(version="latest"),
            manifest_bytes(mandatory="false"),
            manifest_bytes(summary=""),
            manifest_bytes(changelog=[]),
            manifest_bytes(changelog=["Valid", ""]),
            manifest_bytes(released_at="2026-08-09Z"),
            manifest_bytes(released_at="2026-08-09T01:51:24-03:00"),
        )
        for value in invalid_values:
            with self.subTest(value=value[:60]):
                with self.assertRaises(UpdateManifestError):
                    parse_update_manifest(value)

    def test_manifest_download_is_bounded(self) -> None:
        with self.assertRaises(UpdateManifestError):
            parse_update_manifest(b"{" + b" " * MAX_MANIFEST_BYTES + b"}")


class _Cancellable:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeHttp:
    def __init__(
        self,
        *,
        status: int = 200,
        data: bytes = b"",
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.data = data
        self.error = error
        self.headers: dict[str, str] = {}

    def request(
        self,
        _method: str,
        _url: str,
        callback: object,
        *,
        headers: dict[str, str],
    ) -> _Cancellable:
        self.headers = headers
        callback(self.status, self.data, self.error)
        return _Cancellable()


class UpdateCheckerTests(unittest.TestCase):
    def test_network_and_http_failures_become_non_fatal_results(self) -> None:
        for fake in (
            _FakeHttp(error=RuntimeError("offline")),
            _FakeHttp(status=503),
            _FakeHttp(data=b"invalid"),
        ):
            results = []
            UpdateChecker(http=fake).check(results.append)
            self.assertEqual(len(results), 1)
            self.assertIsNotNone(results[0].error)

    def test_checker_uses_the_canonical_json_and_releases_urls(self) -> None:
        fake = _FakeHttp(data=manifest_bytes(version="0.1.17"))
        results = []
        checker = UpdateChecker(http=fake)
        checker.check(results.append, current_version="0.1.17")
        self.assertEqual(checker.url, VERSION_MANIFEST_URL)
        self.assertIn("raw.githubusercontent.com/ehstbr/PyNextCloud-Sync", checker.url)
        self.assertEqual(
            RELEASES_URL,
            "https://github.com/ehstbr/PyNextCloud-Sync/releases/latest",
        )
        self.assertEqual(fake.headers["Cache-Control"], "no-cache")
        self.assertFalse(results[0].update_available)


if __name__ == "__main__":
    unittest.main()
