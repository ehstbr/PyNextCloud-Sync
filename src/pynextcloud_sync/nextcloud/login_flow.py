from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

from gi.repository import Gio, GLib

from .device_identity import authorization_name
from .http import HttpClient, parse_json


@dataclass(frozen=True)
class LoginFlowResult:
    server: str
    login_name: str
    app_password: str


class LoginFlowV2:
    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient(user_agent=authorization_name())
        self.poll_endpoint: str | None = None
        self.poll_token: str | None = None
        self.login_url: str | None = None
        self._poll_source = 0
        self._cancelled = False
        self._poll_count = 0
        self._poll_in_flight = False
        self._poll_cancellable: Gio.Cancellable | None = None
        self._callback: Callable[[LoginFlowResult | None, Exception | None], None] | None = None

    def start(
        self,
        server: str,
        callback: Callable[[LoginFlowResult | None, Exception | None], None],
    ) -> None:
        self.cancel()
        self._cancelled = False
        self._poll_count = 0
        self._callback = callback
        url = f"{server.rstrip('/')}/index.php/login/v2"

        def initiated(status: int, body: bytes, error: Exception | None) -> None:
            if self._cancelled:
                return
            if error or not 200 <= status < 300:
                self.cancel()
                callback(None, error or RuntimeError(f"Login Flow returned HTTP {status}."))
                return
            try:
                data = parse_json(body)
                self.poll_endpoint = data["poll"]["endpoint"]
                self.poll_token = data["poll"]["token"]
                self.login_url = data["login"]
                Gio.AppInfo.launch_default_for_uri(self.login_url, None)
                self._poll_source = GLib.timeout_add_seconds(2, self._poll)
            except Exception as exc:
                self.cancel()
                callback(None, RuntimeError(f"Invalid Login Flow response: {exc}"))

        self.http.request("POST", url, initiated)

    def reopen_browser(self) -> None:
        if self.login_url:
            Gio.AppInfo.launch_default_for_uri(self.login_url, None)

    def cancel(self) -> None:
        self._cancelled = True
        if self._poll_source:
            GLib.source_remove(self._poll_source)
            self._poll_source = 0
        if self._poll_cancellable:
            self._poll_cancellable.cancel()
            self._poll_cancellable = None
        self._poll_in_flight = False
        self.poll_endpoint = None
        self.poll_token = None
        self.login_url = None
        self._callback = None

    def _poll(self) -> bool:
        if self._cancelled or not self.poll_endpoint or not self.poll_token:
            return GLib.SOURCE_REMOVE
        if self._poll_in_flight:
            return GLib.SOURCE_CONTINUE
        self._poll_count += 1
        if self._poll_count > 600:
            callback = self._callback
            self.cancel()
            if callback:
                callback(None, TimeoutError("Browser authorization expired after 20 minutes."))
            return GLib.SOURCE_REMOVE
        body = urlencode({"token": self.poll_token}).encode("utf-8")
        self._poll_in_flight = True

        def polled(status: int, response: bytes, error: Exception | None) -> None:
            self._poll_in_flight = False
            self._poll_cancellable = None
            if self._cancelled:
                return
            if error:
                return
            if status == 404:
                return
            if not 200 <= status < 300:
                self.cancel()
                if self._callback:
                    self._callback(None, RuntimeError(f"Login authorization returned HTTP {status}."))
                return
            try:
                data = parse_json(response)
                result = LoginFlowResult(data["server"], data["loginName"], data["appPassword"])
            except Exception as exc:
                self.cancel()
                if self._callback:
                    self._callback(None, RuntimeError(f"Invalid authorization response: {exc}"))
                return
            callback = self._callback
            self.cancel()
            if callback:
                callback(result, None)

        cancellable = self.http.request("POST", self.poll_endpoint, polled, body=body)
        if self._poll_in_flight:
            self._poll_cancellable = cancellable
        return GLib.SOURCE_CONTINUE
