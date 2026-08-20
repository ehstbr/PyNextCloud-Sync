from __future__ import annotations

from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from pynextcloud_sync import APP_NAME
from pynextcloud_sync.core.autostart import AutostartManager
from pynextcloud_sync.nextcloud.api import (
    AccountDetails,
    NextcloudApi,
    NextcloudRateLimitError,
)
from pynextcloud_sync.nextcloud.command import find_nextcloudcmd
from pynextcloud_sync.nextcloud.device_identity import authorization_name
from pynextcloud_sync.nextcloud.login_flow import LoginFlowResult, LoginFlowV2
from pynextcloud_sync.storage.config import ConfigurationError, normalize_server_url
from pynextcloud_sync.storage.remote_details import clear_remote_details
from pynextcloud_sync.util.i18n import _
from pynextcloud_sync.util.paths import default_sync_root


class SetupWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        application: Gtk.Application,
        config: object,
        credentials: object,
        on_complete: Callable[[], None],
    ) -> None:
        super().__init__(application=application, title=_("Set Up PyNextCloud Sync"))
        self.set_default_size(620, 650)
        self.connect("close-request", self._on_close_request)
        self.config = config
        self.credentials = credentials
        self.on_complete = on_complete
        self.api = NextcloudApi()
        self.login_flow = LoginFlowV2()
        self.server = ""
        self.username = ""
        self.authentication_type = "manual"

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_title=False)
        toolbar.add_top_bar(header)
        self.stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
            transition_duration=250,
        )
        toolbar.set_content(self.stack)
        self.set_content(toolbar)
        self._build_welcome()
        self._build_server()
        self._build_authentication()
        self._build_folder()
        self._build_summary()
        self.stack.set_visible_child_name("welcome")

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        self.get_application().quit()
        return False

    def _page(self) -> tuple[Gtk.Box, Gtk.Box]:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        clamp = Adw.Clamp(maximum_size=480, tightening_threshold=360, vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(36)
        content.set_margin_bottom(36)
        content.set_margin_start(18)
        content.set_margin_end(18)
        clamp.set_child(content)
        outer.append(clamp)
        return outer, content

    def _build_welcome(self) -> None:
        page, content = self._page()
        status = Adw.StatusPage(
            icon_name="com.eduhcommerce.PyNextCloudSync",
            title=APP_NAME,
            description=_("A lightweight desktop synchronizer for Nextcloud."),
        )
        status.set_vexpand(True)
        content.append(status)
        description = Gtk.Label(
            label=_("Your complete Nextcloud file tree will be stored physically on this computer and synchronized in both directions."),
            wrap=True,
            justify=Gtk.Justification.CENTER,
            css_classes=["dim-label"],
        )
        content.append(description)
        if not find_nextcloudcmd():
            warning = Adw.Banner(
                title=_("nextcloudcmd is missing. Install the nextcloud-desktop-cmd package before the first synchronization."),
                revealed=True,
            )
            content.append(warning)
        start = Gtk.Button(label=_("Get Started"), css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER)
        start.connect("clicked", lambda _button: self.stack.set_visible_child_name("server"))
        content.append(start)
        self.stack.add_named(page, "welcome")

    def _build_server(self) -> None:
        page, content = self._page()
        content.append(Gtk.Label(label=_("Connect to Nextcloud"), xalign=0, css_classes=["title-1"]))
        content.append(
            Gtk.Label(
                label=_("Enter the address you normally use to open Nextcloud in a browser."),
                wrap=True,
                xalign=0,
                css_classes=["dim-label"],
            )
        )
        group = Adw.PreferencesGroup()
        self.server_entry = Adw.EntryRow(title=_("Nextcloud server URL"))
        self.server_entry.set_text("https://")
        group.add(self.server_entry)
        self.trust_invalid = Adw.SwitchRow(
            title=_("Allow invalid or self-signed certificates"),
            subtitle=_("This weakens connection security. Enable only for a server you trust."),
        )
        group.add(self.trust_invalid)
        content.append(group)
        self.server_error = Gtk.Label(xalign=0, wrap=True, css_classes=["error"])
        content.append(self.server_error)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        back = Gtk.Button(label=_("Back"))
        back.connect("clicked", lambda _button: self.stack.set_visible_child_name("welcome"))
        actions.append(back)
        next_button = Gtk.Button(label=_("Continue"), css_classes=["suggested-action"])
        next_button.connect("clicked", self._server_continue)
        actions.append(next_button)
        content.append(actions)
        self.stack.add_named(page, "server")

    def _build_authentication(self) -> None:
        page, content = self._page()
        content.append(Gtk.Label(label=_("Sign In"), xalign=0, css_classes=["title-1"]))
        browser_group = Adw.PreferencesGroup()
        browser_row = Adw.ActionRow(
            title=_("Sign in with browser"),
            subtitle=_("Recommended. Supports two-factor authentication."),
            icon_name="web-browser-symbolic",
            activatable=True,
        )
        browser_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        browser_row.connect("activated", self._browser_login)
        browser_group.add(browser_row)
        content.append(browser_group)
        self.waiting_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        self.waiting_box.append(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER))
        self.waiting_box.append(
            Gtk.Label(label=_("Waiting for authorization in your browser…"), wrap=True)
        )
        waiting_actions = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        reopen = Gtk.Button(label=_("Open Browser Again"))
        reopen.connect("clicked", lambda _button: self.login_flow.reopen_browser())
        waiting_actions.append(reopen)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", self._cancel_browser)
        waiting_actions.append(cancel)
        self.waiting_box.append(waiting_actions)
        content.append(self.waiting_box)

        manual = Adw.PreferencesGroup(title=_("Manual Sign In"))
        self.username_entry = Adw.EntryRow(title=_("Username"))
        self.password_entry = Adw.PasswordEntryRow(title=_("Password or app password"))
        manual.add(self.username_entry)
        manual.add(self.password_entry)
        content.append(manual)
        self.auth_error = Gtk.Label(xalign=0, wrap=True, css_classes=["error"])
        content.append(self.auth_error)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        back = Gtk.Button(label=_("Back"))
        back.connect("clicked", lambda _button: self.stack.set_visible_child_name("server"))
        actions.append(back)
        self.manual_button = Gtk.Button(label=_("Sign In Manually"), css_classes=["suggested-action"])
        self.manual_button.connect("clicked", self._manual_login)
        actions.append(self.manual_button)
        content.append(actions)
        self.stack.add_named(page, "authentication")

    def _build_folder(self) -> None:
        page, content = self._page()
        content.append(Gtk.Label(label=_("Choose Local Folder"), xalign=0, css_classes=["title-1"]))
        content.append(
            Gtk.Label(
                label=_("The complete file tree from your account will be mirrored into this single folder."),
                wrap=True,
                xalign=0,
                css_classes=["dim-label"],
            )
        )
        group = Adw.PreferencesGroup()
        self.folder_entry = Adw.EntryRow(title=_("Local NextCloud folder"))
        self.folder_entry.set_text(str(default_sync_root()))
        choose = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
        choose.connect("clicked", self._choose_folder)
        self.folder_entry.add_suffix(choose)
        group.add(self.folder_entry)
        content.append(group)
        self.folder_error = Gtk.Label(xalign=0, wrap=True, css_classes=["error"])
        content.append(self.folder_error)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        back = Gtk.Button(label=_("Back"))
        back.connect("clicked", lambda _button: self.stack.set_visible_child_name("authentication"))
        actions.append(back)
        next_button = Gtk.Button(label=_("Review Setup"), css_classes=["suggested-action"])
        next_button.connect("clicked", self._folder_continue)
        actions.append(next_button)
        content.append(actions)
        self.stack.add_named(page, "folder")

    def _build_summary(self) -> None:
        page, content = self._page()
        content.append(Gtk.Label(label=_("Ready for Safety Review"), xalign=0, css_classes=["title-1"]))
        self.summary_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        content.append(self.summary_list)
        defaults = Gtk.Label(
            label=_("Before automatic synchronization is enabled, both sides will be analyzed in an isolated safety step and you will choose how existing content is merged."),
            wrap=True,
            xalign=0,
            css_classes=["dim-label"],
        )
        content.append(defaults)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        back = Gtk.Button(label=_("Back"))
        back.connect("clicked", lambda _button: self.stack.set_visible_child_name("folder"))
        actions.append(back)
        start = Gtk.Button(label=_("Analyze Both Sides Safely"), css_classes=["suggested-action"])
        start.connect("clicked", self._start_syncing)
        actions.append(start)
        content.append(actions)
        self.stack.add_named(page, "summary")

    def _server_continue(self, _button: Gtk.Button) -> None:
        try:
            self.server = normalize_server_url(self.server_entry.get_text())
        except ConfigurationError as exc:
            self.server_error.set_text(str(exc))
            return
        trust = self.trust_invalid.get_active()
        self.api.http.trust_invalid_certificates = trust
        self.login_flow.http.trust_invalid_certificates = trust
        self.server_error.set_text("")
        self.stack.set_visible_child_name("authentication")

    def _browser_login(self, _row: Adw.ActionRow) -> None:
        self.auth_error.set_text("")
        self.waiting_box.set_visible(True)
        self.login_flow.start(self.server, self._browser_finished)

    def _cancel_browser(self, _button: Gtk.Button) -> None:
        self.login_flow.cancel()
        self.waiting_box.set_visible(False)

    def _browser_finished(self, result: LoginFlowResult | None, error: Exception | None) -> None:
        self.waiting_box.set_visible(False)
        if error or not result:
            self.auth_error.set_text(str(error or _("Browser sign-in was cancelled.")))
            return
        try:
            self.server = normalize_server_url(result.server)
        except ConfigurationError as exc:
            self.auth_error.set_text(str(exc))
            return
        self.username = result.login_name
        self.authentication_type = "browser"
        self._store_secret(result.app_password)

    def _manual_login(self, _button: Gtk.Button) -> None:
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text()
        if not username or not password:
            self.auth_error.set_text(_("Enter a username and password or app password."))
            return
        self.manual_button.set_sensitive(False)
        self.auth_error.set_text(_("Checking account…"))

        def validated(
            ok: bool,
            _account_details: AccountDetails | None,
            error: Exception | None,
        ) -> None:
            self.manual_button.set_sensitive(True)
            if not ok:
                if isinstance(error, NextcloudRateLimitError):
                    self.auth_error.set_text(
                        _(
                            "Nextcloud temporarily limited sign-in requests. Wait a moment and try again."
                        )
                    )
                else:
                    self.auth_error.set_text(str(error or _("Could not sign in.")))
                return
            self.username = username
            self.authentication_type = "manual"
            self._store_secret(password)

        self.api.validate_credentials(self.server, username, password, validated)

    def _store_secret(self, password: str) -> None:
        self.auth_error.set_text(_("Saving account securely…"))

        def stored(ok: bool, error: Exception | None) -> None:
            if not ok:
                self.auth_error.set_text(str(error or _("Could not store the account password.")))
                return
            self.auth_error.set_text("")
            self.password_entry.set_text("")
            self.stack.set_visible_child_name("folder")

        self.credentials.store(self.server, self.username, password, stored)

    def _choose_folder(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title=_("Choose NextCloud Folder"), modal=True)
        dialog.set_initial_folder(Gio.File.new_for_path(self.folder_entry.get_text()))
        dialog.select_folder(self, None, self._folder_chosen)

    def _folder_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            folder = dialog.select_folder_finish(result)
            if folder and folder.get_path():
                self.folder_entry.set_text(folder.get_path())
        except GLib.Error:
            pass

    def _folder_continue(self, _button: Gtk.Button) -> None:
        root = Path(self.folder_entry.get_text()).expanduser()
        if not root.is_absolute():
            self.folder_error.set_text(_("Choose an absolute local folder."))
            return
        self.folder_error.set_text("")
        while row := self.summary_list.get_first_child():
            self.summary_list.remove(row)
        for title, subtitle, icon in (
            (_("Server"), self.server, "network-server-symbolic"),
            (_("Account"), self.username, "avatar-default-symbolic"),
            (_("Local Folder"), str(root), "folder-symbolic"),
            (_("Local Detection"), _("Filesystem monitor"), "folder-saved-search-symbolic"),
            (_("Remote Detection"), _("Server push + every 10 minutes"), "network-transmit-receive-symbolic"),
        ):
            self.summary_list.append(Adw.ActionRow(title=title, subtitle=subtitle, icon_name=icon))
        self.stack.set_visible_child_name("summary")

    def _start_syncing(self, _button: Gtk.Button) -> None:
        self._finish_setup()

    def _finish_setup(self) -> None:
        root = Path(self.folder_entry.get_text()).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.config.data["account"] = {
            "server_url": self.server,
            "login_name": self.username,
            "authentication_type": self.authentication_type,
            "authorization_name": (
                authorization_name()
                if self.authentication_type == "browser"
                else None
            ),
            "local_root": str(root),
        }
        self.config.data["network"]["trust_invalid_certificates"] = (
            self.trust_invalid.get_active()
        )
        self.config.data["safety"]["bootstrap_complete"] = False
        self.config.data["safety"]["bootstrap_completed_at"] = None
        clear_remote_details(self.config)
        self.config.save()
        AutostartManager().set_enabled(self.config.data["general"]["autostart"])
        self.on_complete()
