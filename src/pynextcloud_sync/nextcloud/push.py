from __future__ import annotations

import json
from typing import Any, Callable

import gi

gi.require_version("Soup", "3.0")
from gi.repository import Gio, GLib, Soup

from pynextcloud_sync.core.state import PushState
from pynextcloud_sync.util.i18n import _

from .http import HttpClient, basic_authorization, parse_json
from .push_protocol import PushEndpoints, parse_push_capability, validate_push_transport



class NotifyPushClient:
    """Nextcloud notify_push client. It only emits file-change hints."""

    BACKOFF_SECONDS = (2, 5, 10, 30, 60, 300)

    def __init__(
        self,
        on_file_notification: Callable[[], None],
        on_state: Callable[[PushState, str], None],
        logger: Any,
        http: HttpClient | None = None,
    ) -> None:
        self.on_file_notification = on_file_notification
        self.on_state = on_state
        self.logger = logger
        self.http = http or HttpClient()
        self.server = ""
        self.username = ""
        self.password = ""
        self.enabled = False
        self.online = True
        self.connection: Soup.WebsocketConnection | None = None
        self.endpoints: PushEndpoints | None = None
        self._pre_auth_token: str | None = None
        self._backoff_index = 0
        self._reconnect_source = 0
        self._generation = 0
        self._intentional_close = False
        self._authenticated = False
        self._auth_mode = ""
        self._force_password_auth = False

    def configure(self, server: str, username: str, password: str, enabled: bool) -> None:
        changed = (server, username, enabled) != (self.server, self.username, self.enabled)
        self.server = server
        self.username = username
        self.password = password
        self.enabled = enabled
        if changed:
            self.disconnect()
        if not enabled:
            self.on_state(PushState.DISABLED, _("Push notifications are disabled."))
        elif self.online:
            self.connect()

    def set_online(self, online: bool) -> None:
        self.online = online
        if not online:
            self.disconnect(keep_enabled=True)
        elif self.enabled:
            self.connect()

    def connect(self) -> None:
        if not self.enabled or not self.online or self.connection is not None:
            return
        self._generation += 1
        generation = self._generation
        self._cancel_reconnect()
        self.on_state(PushState.CONNECTING, _("Discovering server push support…"))
        url = f"{self.server.rstrip('/')}/ocs/v2.php/cloud/capabilities?format=json"
        headers = {
            "Accept": "application/json",
            "OCS-APIREQUEST": "true",
            "Authorization": basic_authorization(self.username, self.password),
        }

        def discovered(status: int, body: bytes, error: Exception | None) -> None:
            if generation != self._generation or not self.enabled:
                return
            if error:
                self._schedule_reconnect(str(error))
                return
            if status in {401, 403}:
                self.on_state(PushState.AUTH_REQUIRED, _("Push authentication failed."))
                return
            if not 200 <= status < 300:
                self._schedule_reconnect(f"Capabilities returned HTTP {status}.")
                return
            try:
                endpoints = parse_push_capability(parse_json(body))
                if endpoints is None:
                    self.on_state(PushState.UNSUPPORTED, _("This server does not offer notify_push."))
                    return
                validate_push_transport(self.server, endpoints.websocket)
                self.endpoints = endpoints
            except Exception as exc:
                self._schedule_reconnect(str(exc))
                return
            if self.endpoints.pre_auth and not self._force_password_auth:
                self._request_pre_auth(generation)
            else:
                # Do not reuse a pre-auth token when falling back to direct
                # app-password authentication after an early socket close.
                self._pre_auth_token = None
                self._open_websocket(generation)

        self.http.request("GET", url, discovered, headers=headers)

    def _request_pre_auth(self, generation: int) -> None:
        assert self.endpoints and self.endpoints.pre_auth
        headers = {
            "Accept": "application/json",
            "OCS-APIREQUEST": "true",
            "Authorization": basic_authorization(self.username, self.password),
        }

        def received(status: int, body: bytes, error: Exception | None) -> None:
            if generation != self._generation:
                return
            if error or not 200 <= status < 300:
                self.logger.warning("Push pre-authentication unavailable; using protocol fallback.")
                self._pre_auth_token = None
                self._open_websocket(generation)
                return
            try:
                text = body.decode("utf-8").strip()
                if text.startswith("{"):
                    data = json.loads(text)
                    text = str(data.get("token") or data.get("ocs", {}).get("data", {}).get("token") or "")
                self._pre_auth_token = text or None
            except Exception:
                self._pre_auth_token = None
            self._open_websocket(generation)

        self.http.request("POST", self.endpoints.pre_auth, received, headers=headers)

    def _open_websocket(self, generation: int) -> None:
        if not self.endpoints or generation != self._generation:
            return
        message = Soup.Message.new("GET", self.endpoints.websocket)
        if message is None:
            self._schedule_reconnect("Invalid WebSocket endpoint.")
            return
        self.http.prepare_message(message)

        def opened(session: Soup.Session, result: Gio.AsyncResult, _data: object = None) -> None:
            if generation != self._generation:
                return
            try:
                connection = session.websocket_connect_finish(result)
            except GLib.Error as exc:
                self._schedule_reconnect(str(exc))
                return
            self.connection = connection
            self._authenticated = False
            connection.connect("message", self._on_message)
            connection.connect("closed", self._on_closed)
            connection.connect("error", self._on_error)
            if self._pre_auth_token:
                self._auth_mode = "pre_auth"
                connection.send_text(self._pre_auth_token)
            else:
                self._auth_mode = "password"
                connection.send_text(self.username)
                connection.send_text(self.password)

        self.http.session.websocket_connect_async(
            message, None, None, GLib.PRIORITY_DEFAULT, None, opened, None
        )

    def _on_message(
        self,
        _connection: Soup.WebsocketConnection,
        data_type: Soup.WebsocketDataType,
        message: GLib.Bytes,
    ) -> None:
        if data_type != Soup.WebsocketDataType.TEXT:
            return
        text = message.get_data().decode("utf-8", errors="replace").strip()
        if text == "authenticated":
            self._authenticated = True
            self._force_password_auth = False
            self._backoff_index = 0
            self.on_state(PushState.CONNECTED, _("Connected"))
            self.logger.info("notify_push authenticated.")
        elif text in {"notify_file", "notify_file_id"} or text.startswith("notify_file_id "):
            self.logger.info("Remote file notification received from notify_push.")
            self.on_file_notification()
        elif text in {"invalid credentials", "authentication failed"}:
            self.on_state(PushState.AUTH_REQUIRED, _("Push authentication failed."))

    def _on_closed(self, _connection: Soup.WebsocketConnection) -> None:
        if _connection is not self.connection:
            if self._intentional_close:
                self._intentional_close = False
            return
        self.connection = None
        if self._intentional_close:
            self._intentional_close = False
            return
        if self.enabled and self.online:
            details = "Push connection closed."
            if hasattr(_connection, "get_close_code"):
                code = int(_connection.get_close_code())
                close_data = _connection.get_close_data() or ""
                details = f"Push connection closed with code {code}"
                if close_data:
                    details += f": {close_data}"
                details += "."
            if not self._authenticated and self._auth_mode == "pre_auth":
                self._force_password_auth = True
                self._pre_auth_token = None
                details += " Retrying with direct app-password authentication."
            elif not self._authenticated and self._auth_mode == "password":
                self._force_password_auth = False
            self._schedule_reconnect(details)

    def _on_error(self, _connection: Soup.WebsocketConnection, error: GLib.Error) -> None:
        self.logger.warning("notify_push connection error: %s", error)

    def _schedule_reconnect(self, reason: str) -> None:
        if not self.enabled or not self.online:
            return
        delay = self.BACKOFF_SECONDS[min(self._backoff_index, len(self.BACKOFF_SECONDS) - 1)]
        self._backoff_index += 1
        self.on_state(PushState.RECONNECTING, _("Reconnecting in {seconds} seconds").format(seconds=delay))
        self.logger.warning("notify_push unavailable: %s", reason)
        self._cancel_reconnect()
        self._reconnect_source = GLib.timeout_add_seconds(delay, self._reconnect)

    def _reconnect(self) -> bool:
        self._reconnect_source = 0
        self.connection = None
        self.connect()
        return GLib.SOURCE_REMOVE

    def _cancel_reconnect(self) -> None:
        if self._reconnect_source:
            GLib.source_remove(self._reconnect_source)
            self._reconnect_source = 0

    def disconnect(self, keep_enabled: bool = False) -> None:
        self._generation += 1
        self._cancel_reconnect()
        if self.connection is not None:
            try:
                self._intentional_close = True
                self.connection.close(Soup.WebsocketCloseCode.NORMAL, "Application state changed")
            except GLib.Error:
                pass
            self.connection = None
        self.endpoints = None
        self._pre_auth_token = None
        self._authenticated = False
        self._auth_mode = ""
        self._force_password_auth = False
        if not keep_enabled:
            self.on_state(PushState.DISABLED, _("Disconnected"))
