from __future__ import annotations

import base64
import json
from typing import Any, Callable

import gi

gi.require_version("Soup", "3.0")
from gi.repository import Gio, GLib, Soup

from pynextcloud_sync import VERSION


HttpCallback = Callable[[int, bytes, Exception | None], None]


def basic_authorization(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


class HttpClient:
    def __init__(self, user_agent: str | None = None, *, timeout: int = 30) -> None:
        user_agent = user_agent or f"PyNextCloud-Sync/{VERSION}"
        self.session = Soup.Session(user_agent=user_agent, timeout=timeout)
        self.trust_invalid_certificates = False

    def prepare_message(self, message: Soup.Message) -> Soup.Message:
        if self.trust_invalid_certificates:
            message.connect("accept-certificate", lambda *_args: True)
        return message

    def request(
        self,
        method: str,
        url: str,
        callback: HttpCallback,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        content_type: str = "application/x-www-form-urlencoded",
    ) -> Gio.Cancellable:
        message = Soup.Message.new(method, url)
        if message is None:
            callback(0, b"", ValueError("Invalid request URL."))
            return Gio.Cancellable()
        self.prepare_message(message)
        for key, value in (headers or {}).items():
            message.get_request_headers().replace(key, value)
        if body is not None:
            message.set_request_body_from_bytes(content_type, GLib.Bytes.new(body))
        cancellable = Gio.Cancellable()

        def finished(session: Soup.Session, result: Gio.AsyncResult, _data: object = None) -> None:
            try:
                response = session.send_and_read_finish(result)
                callback(message.get_status(), response.get_data(), None)
            except GLib.Error as exc:
                callback(message.get_status(), b"", RuntimeError(str(exc)))

        self.session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, cancellable, finished, None
        )
        return cancellable


def parse_json(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))
