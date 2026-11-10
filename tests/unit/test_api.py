from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


API_SOURCE = (
    Path(__file__).parents[2]
    / "src"
    / "pynextcloud_sync"
    / "nextcloud"
    / "api.py"
)


def basic_authorization(username: str, password: str) -> str:
    return f"Basic {username}:{password}"


class FakeHttpClient:
    def __init__(self, responses: list[tuple[int, object, Exception | None]]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        callback: object,
        *,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> None:
        self.requests.append((method, url, headers or {}))
        status, payload, error = self.responses.pop(0)
        body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )
        callback(status, body, error)


def load_api_module():
    fake_http = types.ModuleType("pynextcloud_sync.nextcloud.http")
    fake_http.HttpClient = object
    fake_http.basic_authorization = basic_authorization
    fake_http.parse_json = lambda data: json.loads(data.decode("utf-8"))
    spec = importlib.util.spec_from_file_location(
        "pynextcloud_sync.nextcloud.api_test_double", API_SOURCE
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "pynextcloud_sync.nextcloud.http": fake_http,
            spec.name: module,
        },
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class NextcloudApiTests(unittest.TestCase):
    def test_server_details_are_loaded_from_status_endpoint(self) -> None:
        module = load_api_module()
        http = FakeHttpClient(
            [
                (
                    200,
                    {
                        "productname": "Nextcloud",
                        "versionstring": "34.0.1",
                        "maintenance": False,
                        "needsDbUpgrade": False,
                    },
                    None,
                )
            ]
        )
        results: list[tuple[object, object]] = []

        module.NextcloudApi(http).get_server_details(
            "https://cloud.example", lambda details, error: results.append((details, error))
        )

        self.assertEqual(results[0][0].version, "34.0.1")
        self.assertIsNone(results[0][1])
        self.assertTrue(http.requests[0][1].endswith("/status.php"))

    def test_protected_root_probe_only_requests_depth_zero_and_uses_successful_properties(self):
        module = load_api_module()
        http = FakeHttpClient([(207, b"""<d:multistatus xmlns:d="DAV:"><d:response>
            <d:propstat><d:prop><d:getetag>"ignored"</d:getetag></d:prop>
                <d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>
            <d:propstat><d:prop><d:getetag>"original"</d:getetag>
                <d:quota-used-bytes>2048</d:quota-used-bytes></d:prop>
                <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
            </d:response></d:multistatus>""", None)])
        results = []
        module.NextcloudApi(http).get_protected_root_properties(
            "https://cloud.example/nextcloud/", "alice", "fixture",
            lambda tag, used: results.append((tag, used)),
        )
        method, url, headers = http.requests[0]
        self.assertEqual(method, "PROPFIND")
        self.assertEqual(url, "https://cloud.example/nextcloud/remote.php/webdav/")
        self.assertEqual(headers["Depth"], "0")
        self.assertEqual(results, [('"original"', 2048)])

    def test_protected_root_probe_treats_rate_limit_and_bad_xml_as_unavailable(self):
        module = load_api_module()
        http = FakeHttpClient([(429, b"", None), (207, b"invalid", None)])
        results = []
        for _ in range(2):
            module.NextcloudApi(http).get_protected_root_properties(
                "https://cloud.example", "alice", "fixture",
                lambda tag, used: results.append((tag, used)),
            )
        self.assertEqual(results, [(None, None), (None, None)])

    def test_account_details_include_identity_and_quota(self) -> None:
        module = load_api_module()
        http = FakeHttpClient(
            [
                (
                    200,
                    {
                        "ocs": {
                            "data": {
                                "display-name": "Alice",
                                "email": "alice@example.com",
                                "quota": {"used": 10, "total": 100},
                            }
                        }
                    },
                    None,
                )
            ]
        )
        results: list[tuple[object, object]] = []

        module.NextcloudApi(http).get_account_details(
            "https://cloud.example",
            "alice",
            "secret",
            lambda details, error: results.append((details, error)),
        )

        details, error = results[0]
        self.assertIsNone(error)
        self.assertEqual(details.display_name, "Alice")
        self.assertEqual(details.email, "alice@example.com")
        self.assertEqual((details.quota_used, details.quota_total), (10, 100))

    def test_rejected_account_details_are_reported_as_authentication(self) -> None:
        module = load_api_module()
        http = FakeHttpClient([(401, {}, None)])
        results: list[tuple[object, object]] = []

        module.NextcloudApi(http).get_account_details(
            "https://cloud.example",
            "alice",
            "revoked",
            lambda details, error: results.append((details, error)),
        )

        self.assertIsNone(results[0][0])
        self.assertIsInstance(results[0][1], PermissionError)

    def test_rate_limited_validation_is_reported_as_transient(self) -> None:
        module = load_api_module()
        http = FakeHttpClient([(429, {}, None)])
        results: list[tuple[object, object, object]] = []

        module.NextcloudApi(http).validate_credentials(
            "https://cloud.example",
            "alice",
            "new-app-password",
            lambda ok, details, error: results.append((ok, details, error)),
        )

        ok, details, error = results[0]
        self.assertFalse(ok)
        self.assertIsNone(details)
        self.assertIsInstance(error, module.NextcloudRateLimitError)
        self.assertGreaterEqual(error.retry_after, 1)

    def test_successful_validation_returns_the_account_details(self) -> None:
        module = load_api_module()
        http = FakeHttpClient(
            [
                (
                    200,
                    {
                        "ocs": {
                            "data": {
                                "display-name": "Alice",
                                "email": "alice@example.com",
                                "quota": {"used": 10, "total": 100},
                            }
                        }
                    },
                    None,
                )
            ]
        )
        results: list[tuple[object, object, object]] = []

        module.NextcloudApi(http).validate_credentials(
            "https://cloud.example",
            "alice",
            "new-app-password",
            lambda ok, details, error: results.append((ok, details, error)),
        )

        ok, details, error = results[0]
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(details.display_name, "Alice")
        self.assertEqual(details.email, "alice@example.com")
        self.assertEqual((details.quota_used, details.quota_total), (10, 100))


if __name__ == "__main__":
    unittest.main()
