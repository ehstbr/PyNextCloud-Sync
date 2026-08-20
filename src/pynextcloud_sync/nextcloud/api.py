from __future__ import annotations

from typing import Any, Callable

from .http import HttpClient, basic_authorization, parse_json
from .models import AccountDetails, ServerDetails


class NextcloudRateLimitError(RuntimeError):
    """A temporary server limit that must not invalidate valid credentials."""

    def __init__(self, retry_after: int = 10) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__("Nextcloud temporarily limited requests.")


class NextcloudApi:
    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient()

    def get_server_details(
        self,
        server: str,
        callback: Callable[[ServerDetails | None, Exception | None], None],
    ) -> None:
        url = f"{server.rstrip('/')}/status.php"

        def done(status: int, body: bytes, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return
            if status < 200 or status >= 300:
                callback(None, RuntimeError(f"Nextcloud returned HTTP {status}."))
                return
            try:
                payload = parse_json(body)
                callback(
                    ServerDetails(
                        product_name=str(payload.get("productname") or "Nextcloud"),
                        version=str(
                            payload.get("versionstring")
                            or payload.get("version")
                            or ""
                        ),
                        maintenance=bool(payload.get("maintenance", False)),
                        needs_database_upgrade=bool(
                            payload.get("needsDbUpgrade", False)
                        ),
                    ),
                    None,
                )
            except Exception as exc:
                callback(None, RuntimeError(f"Invalid Nextcloud response: {exc}"))

        self.http.request("GET", url, done, headers={"Accept": "application/json"})

    def get_account_details(
        self,
        server: str,
        username: str,
        password: str,
        callback: Callable[[AccountDetails | None, Exception | None], None],
    ) -> None:
        url = f"{server.rstrip('/')}/ocs/v2.php/cloud/user?format=json"
        headers = {
            "Accept": "application/json",
            "OCS-APIREQUEST": "true",
            "Authorization": basic_authorization(username, password),
        }

        def done(status: int, body: bytes, error: Exception | None) -> None:
            if error:
                callback(None, error)
                return
            if status in {401, 403}:
                callback(None, PermissionError("The server rejected these credentials."))
                return
            if status == 429:
                callback(None, NextcloudRateLimitError())
                return
            if status < 200 or status >= 300:
                callback(None, RuntimeError(f"Nextcloud returned HTTP {status}."))
                return
            try:
                payload = parse_json(body)
                callback(self._parse_account_details(payload, username), None)
            except Exception as exc:
                callback(None, RuntimeError(f"Invalid Nextcloud response: {exc}"))

        self.http.request("GET", url, done, headers=headers)

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_account_details(
        cls, payload: Any, username: str
    ) -> AccountDetails:
        data = payload.get("ocs", {}).get("data", {})
        quota = data.get("quota") or {}
        return AccountDetails(
            display_name=str(
                data.get("display-name") or data.get("displayname") or username
            ),
            email=str(data.get("email") or ""),
            quota_used=cls._optional_integer(quota.get("used")),
            quota_total=cls._optional_integer(quota.get("total")),
        )

    def validate_credentials(
        self,
        server: str,
        username: str,
        password: str,
        callback: Callable[[bool, AccountDetails | None, Exception | None], None],
    ) -> None:
        url = f"{server.rstrip('/')}/ocs/v2.php/cloud/user?format=json"
        headers = {
            "Accept": "application/json",
            "OCS-APIREQUEST": "true",
            "Authorization": basic_authorization(username, password),
        }

        def done(status: int, body: bytes, error: Exception | None) -> None:
            if error:
                callback(False, None, error)
                return
            if status in {401, 403}:
                callback(False, None, PermissionError("The server rejected these credentials."))
                return
            if status == 429:
                callback(False, None, NextcloudRateLimitError())
                return
            if status < 200 or status >= 300:
                callback(False, None, RuntimeError(f"Nextcloud returned HTTP {status}."))
                return
            try:
                payload = parse_json(body)
                callback(True, self._parse_account_details(payload, username), None)
            except Exception as exc:
                callback(False, None, RuntimeError(f"Invalid Nextcloud response: {exc}"))

        self.http.request("GET", url, done, headers=headers)

    def revoke_app_password(
        self,
        server: str,
        username: str,
        password: str,
        callback: Callable[[bool], None],
    ) -> None:
        url = f"{server.rstrip('/')}/ocs/v2.php/core/apppassword"
        headers = {
            "Accept": "application/json",
            "OCS-APIREQUEST": "true",
            "Authorization": basic_authorization(username, password),
        }

        def done(status: int, _body: bytes, _error: Exception | None) -> None:
            callback(200 <= status < 300)

        self.http.request("DELETE", url, done, headers=headers)
