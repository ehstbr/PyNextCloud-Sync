from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from pynextcloud_sync.nextcloud.api import (
    AccountDetails,
    NextcloudApi,
    NextcloudRateLimitError,
)
from pynextcloud_sync.nextcloud.device_identity import authorization_name
from pynextcloud_sync.nextcloud.login_flow import LoginFlowResult, LoginFlowV2
from pynextcloud_sync.storage.config import ConfigurationError, normalize_server_url
from pynextcloud_sync.util.i18n import _


class ReconnectWindow(Adw.ApplicationWindow):
    """Renew only the app password while preserving the configured sync account."""

    def __init__(
        self,
        application: Gtk.Application,
        config: object,
        credentials: object,
        logger: object,
        on_complete: Callable[[AccountDetails], None],
        on_close: Callable[["ReconnectWindow"], None],
        parent: Gtk.Window | None = None,
    ) -> None:
        super().__init__(application=application, title=_("Reconnect Account"))
        self.set_default_size(560, 500)
        if parent:
            self.set_transient_for(parent)
            self.set_modal(True)
        self.config = config
        self.credentials = credentials
        self.logger = logger
        self.on_complete = on_complete
        self.on_close = on_close
        self.api = NextcloudApi()
        self.login_flow = LoginFlowV2()
        self._old_password: str | None = None
        self._pending_result: LoginFlowResult | None = None
        self._attempt_generation = 0
        self._validation_generation = 0
        self._validation_retry_source = 0
        self._rate_limit_count = 0
        self._closed = False
        self.connect("close-request", self._close_requested)

        trust = bool(
            self.config.data.get("network", {}).get(
                "trust_invalid_certificates", False
            )
        )
        self.api.http.trust_invalid_certificates = trust
        self.login_flow.http.trust_invalid_certificates = trust

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        clamp = Adw.Clamp(maximum_size=470, tightening_threshold=360)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        clamp.set_child(content)
        toolbar.set_content(clamp)
        self.set_content(toolbar)

        introduction = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.FILL,
        )
        introduction.append(
            Gtk.Image(
                icon_name="dialog-password-symbolic",
                pixel_size=64,
                halign=Gtk.Align.CENTER,
            )
        )
        title = Gtk.Label(
            label=_("Reconnect Nextcloud Account"),
            wrap=True,
            justify=Gtk.Justification.CENTER,
            halign=Gtk.Align.CENTER,
            css_classes=["title-1"],
        )
        introduction.append(title)
        description = Gtk.Label(
            label=_(
                "Renew the authorization without changing the local folder, synchronization settings, or safety baseline."
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
            xalign=0.5,
            css_classes=["dim-label"],
        )
        description.set_max_width_chars(52)
        introduction.append(description)
        content.append(introduction)

        account = self.config.data["account"]
        account_group = Adw.PreferencesGroup()
        account_group.add(
            Adw.ActionRow(
                title=account["login_name"],
                subtitle=account["server_url"],
                icon_name="avatar-default-symbolic",
            )
        )
        account_group.add(
            Adw.ActionRow(
                title=_("New authorization name"),
                subtitle=authorization_name(),
                icon_name="computer-symbolic",
            )
        )
        content.append(account_group)

        self.error_label = Gtk.Label(
            xalign=0,
            wrap=True,
            css_classes=["error"],
        )
        content.append(self.error_label)

        self.waiting_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            visible=False,
        )
        self.waiting_box.append(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER))
        self.waiting_label = Gtk.Label(
            label=_("Waiting for authorization in your browser…"),
            wrap=True,
        )
        self.waiting_box.append(self.waiting_label)
        waiting_actions = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.reopen_button = Gtk.Button(label=_("Open Browser Again"))
        self.reopen_button.connect(
            "clicked", lambda _button: self.login_flow.reopen_browser()
        )
        waiting_actions.append(self.reopen_button)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", self._cancel_authorization)
        waiting_actions.append(cancel)
        self.waiting_box.append(waiting_actions)
        content.append(self.waiting_box)

        self.authorize_button = Gtk.Button(
            label=_("Authorize in Browser"),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        self.authorize_button.connect("clicked", self._begin_authorization)
        content.append(self.authorize_button)

    def _begin_authorization(self, _button: Gtk.Button) -> None:
        self._clear_validation_retry()
        self._attempt_generation += 1
        generation = self._attempt_generation
        self._rate_limit_count = 0
        self.error_label.set_text("")
        self.authorize_button.set_sensitive(False)
        self.authorize_button.set_visible(False)
        self.waiting_box.set_visible(True)
        self.reopen_button.set_visible(True)
        self.waiting_label.set_text(_("Waiting for authorization in your browser…"))
        account = self.config.data["account"]

        def credential_ready(
            password: str | None, _error: Exception | None
        ) -> None:
            if self._closed or generation != self._attempt_generation:
                return
            self._old_password = password
            self.login_flow.start(account["server_url"], self._browser_finished)

        self.credentials.lookup(
            account["server_url"], account["login_name"], credential_ready
        )

    def _cancel_authorization(self, _button: Gtk.Button) -> None:
        self._clear_validation_retry()
        self._attempt_generation += 1
        self._validation_generation += 1
        self.login_flow.cancel()
        pending_result = self._pending_result
        self._pending_result = None
        if pending_result:
            self.api.revoke_app_password(
                pending_result.server,
                pending_result.login_name,
                pending_result.app_password,
                lambda _revoked: None,
            )
        self.waiting_box.set_visible(False)
        self.authorize_button.set_sensitive(True)
        self.authorize_button.set_visible(True)
        self.error_label.set_text(_("Authorization was canceled."))

    def _browser_finished(
        self,
        result: LoginFlowResult | None,
        error: Exception | None,
    ) -> None:
        if self._closed:
            return
        self.waiting_box.set_visible(False)
        if error or not result:
            self.authorize_button.set_sensitive(True)
            self.authorize_button.set_visible(True)
            self.error_label.set_text(
                str(error or _("Browser sign-in was cancelled."))
            )
            return
        self._pending_result = result
        self._rate_limit_count = 0
        account = self.config.data["account"]
        try:
            returned_server = normalize_server_url(result.server)
        except ConfigurationError as exc:
            self._reject_result(result, str(exc))
            return
        if (
            returned_server != account["server_url"]
            or result.login_name != account["login_name"]
        ):
            self._reject_result(
                result,
                _(
                    "The browser authorized a different server or account. Sign in with the account already configured in PyNextCloud Sync."
                ),
            )
            return
        self._validate_result(result)

    def _validate_result(self, result: LoginFlowResult) -> None:
        self._clear_validation_retry()
        self._validation_generation += 1
        generation = self._validation_generation
        self.error_label.set_text("")
        self.waiting_box.set_visible(True)
        self.reopen_button.set_visible(False)
        self.authorize_button.set_visible(False)
        self.waiting_label.set_text(_("Validating the new authorization…"))
        account = self.config.data["account"]

        def validated(
            ok: bool,
            account_details: AccountDetails | None,
            validation_error: Exception | None,
        ) -> None:
            if self._closed or generation != self._validation_generation:
                return
            if isinstance(validation_error, NextcloudRateLimitError):
                self._validation_limited(result, validation_error)
                return
            if not ok or not account_details:
                self._reject_result(
                    result,
                    str(
                        validation_error
                        or _("The new authorization was rejected.")
                    ),
                )
                return
            self._store_result(result, account_details)

        self.api.validate_credentials(
            account["server_url"],
            account["login_name"],
            result.app_password,
            validated,
        )

    def _validation_limited(
        self,
        result: LoginFlowResult,
        error: NextcloudRateLimitError,
    ) -> None:
        retry_delays = (10, 30, 60, 120, 300)
        delay = max(
            error.retry_after,
            retry_delays[min(self._rate_limit_count, len(retry_delays) - 1)],
        )
        self._rate_limit_count += 1
        self.waiting_box.set_visible(True)
        self.reopen_button.set_visible(False)
        self.authorize_button.set_visible(False)
        self.waiting_label.set_text(
            _(
                "Nextcloud temporarily limited requests. Retrying this same authorization in {seconds} seconds…"
            ).format(seconds=delay)
        )

        def retry() -> bool:
            self._validation_retry_source = 0
            if self._closed or self._pending_result != result:
                return GLib.SOURCE_REMOVE
            self._validate_result(result)
            return GLib.SOURCE_REMOVE

        self._validation_retry_source = GLib.timeout_add_seconds(delay, retry)

    def _clear_validation_retry(self) -> None:
        if self._validation_retry_source:
            GLib.source_remove(self._validation_retry_source)
            self._validation_retry_source = 0

    def _reject_result(self, result: LoginFlowResult, message: str) -> None:
        self._clear_validation_retry()
        self._validation_generation += 1
        if self._pending_result == result:
            self._pending_result = None
        self.api.revoke_app_password(
            result.server,
            result.login_name,
            result.app_password,
            lambda _revoked: None,
        )
        self.waiting_box.set_visible(False)
        self.authorize_button.set_sensitive(True)
        self.authorize_button.set_visible(True)
        self.error_label.set_text(message)

    def _store_result(
        self, result: LoginFlowResult, account_details: AccountDetails
    ) -> None:
        self._clear_validation_retry()
        account = self.config.data["account"]
        self.waiting_label.set_text(_("Saving the new authorization securely…"))

        def stored(ok: bool, error: Exception | None) -> None:
            if self._closed:
                return
            if not ok:
                self._reject_result(
                    result,
                    str(error or _("Could not store the new authorization.")),
                )
                return
            account["authentication_type"] = "browser"
            account["authorization_name"] = authorization_name()
            try:
                self.config.save(notify=False)
            except Exception as exc:
                self.logger.warning(
                    "The renewed authorization was stored, but its display metadata could not be saved: %s",
                    exc,
                )
            old_password = self._old_password
            if old_password and old_password != result.app_password:
                self.api.revoke_app_password(
                    account["server_url"],
                    account["login_name"],
                    old_password,
                    lambda revoked: self.logger.info(
                        "Previous Nextcloud authorization revocation: %s",
                        "completed" if revoked else "not available",
                    ),
                )
            self._pending_result = None
            self.on_complete(account_details)
            self.close()

        self.credentials.store(
            account["server_url"],
            account["login_name"],
            result.app_password,
            stored,
        )

    def _close_requested(self, _window: Gtk.Window) -> bool:
        if not self._closed:
            self._closed = True
            self._clear_validation_retry()
            self._attempt_generation += 1
            self._validation_generation += 1
            self.login_flow.cancel()
            pending_result = self._pending_result
            self._pending_result = None
            if pending_result:
                self.api.revoke_app_password(
                    pending_result.server,
                    pending_result.login_name,
                    pending_result.app_password,
                    lambda _revoked: None,
                )
            self.on_close(self)
        return False
