from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from pynextcloud_sync.core.autostart import AutostartManager
from pynextcloud_sync.core.exclusions import DEFAULT_PATTERNS, InvalidPattern, validate_pattern
from pynextcloud_sync.core.state import AppState, StateSnapshot
from pynextcloud_sync.core.triggers import manual_only
from pynextcloud_sync.nextcloud.api import (
    AccountDetails,
    NextcloudApi,
    NextcloudRateLimitError,
    ServerDetails,
)
from pynextcloud_sync.nextcloud.device_identity import authorization_name
from pynextcloud_sync.storage.config import ConfigurationError
from pynextcloud_sync.storage.remote_details import (
    cached_account_details,
    cached_server_details,
)
from pynextcloud_sync.util.i18n import _


def _spin_row(title: str, lower: int, upper: int, value: int) -> Adw.SpinRow:
    adjustment = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=1, page_increment=5)
    return Adw.SpinRow(title=title, adjustment=adjustment)


class ExclusionsDialog(Adw.Dialog):
    def __init__(self, config: object, on_saved: object) -> None:
        super().__init__(title=_("Excluded Files"), content_width=520, content_height=580)
        self.config = config
        self.on_saved = on_saved
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        done = Gtk.Button(label=_("Done"), css_classes=["suggested-action"])
        done.connect("clicked", lambda _button: self.close())
        header.pack_end(done)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        explanation = Gtk.Label(
            label=_("Only file names, extensions, and wildcard patterns are allowed. Folders and paths cannot be excluded."),
            wrap=True,
            xalign=0,
            css_classes=["dim-label"],
        )
        content.append(explanation)
        self.listbox = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        content.append(self.listbox)
        entry_box = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text=_("Example: *.swp"))
        self.entry.connect("activate", self._add)
        entry_box.append(self.entry)
        add = Gtk.Button(label=_("Add Pattern"), css_classes=["suggested-action"])
        add.connect("clicked", self._add)
        entry_box.append(add)
        content.append(entry_box)
        self.error_label = Gtk.Label(xalign=0, wrap=True, css_classes=["error"])
        content.append(self.error_label)
        restore = Gtk.Button(label=_("Restore Defaults"), halign=Gtk.Align.START)
        restore.connect("clicked", self._restore)
        content.append(restore)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(content)
        toolbar.set_content(scroller)
        self.set_child(toolbar)
        self._refresh()

    def _refresh(self) -> None:
        while row := self.listbox.get_first_child():
            self.listbox.remove(row)
        patterns = self.config.data["sync"]["exclude_patterns"]
        for pattern in patterns:
            row = Adw.ActionRow(title=pattern)
            remove = Gtk.Button(
                icon_name="user-trash-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text=_("Remove pattern"),
                css_classes=["flat"],
            )
            remove.connect("clicked", self._remove, pattern)
            row.add_suffix(remove)
            self.listbox.append(row)

    def _add(self, _widget: Gtk.Widget) -> None:
        try:
            pattern = validate_pattern(self.entry.get_text())
            patterns = self.config.data["sync"]["exclude_patterns"]
            if pattern not in patterns:
                patterns.append(pattern)
                self.config.save()
                self.on_saved()
            self.entry.set_text("")
            self.error_label.set_text("")
            self._refresh()
        except (InvalidPattern, ValueError) as exc:
            self.error_label.set_text(str(exc))

    def _remove(self, _button: Gtk.Button, pattern: str) -> None:
        patterns = self.config.data["sync"]["exclude_patterns"]
        if pattern in patterns:
            patterns.remove(pattern)
            self.config.save()
            self.on_saved()
            self._refresh()

    def _restore(self, _button: Gtk.Button) -> None:
        self.config.data["sync"]["exclude_patterns"] = list(DEFAULT_PATTERNS)
        self.config.save()
        self.on_saved()
        self._refresh()


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(
        self,
        application: Gtk.Application,
        config: object,
        runtime: object,
        desktop_integration: object,
        on_reconnect_account: object,
        on_remove_account: object,
        on_account_details: object,
        on_server_details: object,
    ) -> None:
        super().__init__(application=application, title=_("Settings"))
        self.set_default_size(720, 640)
        self.config = config
        self.runtime = runtime
        self.credentials = runtime.credentials
        self.desktop_integration = desktop_integration
        self.on_reconnect_account = on_reconnect_account
        self.on_remove_account = on_remove_account
        self.on_account_details = on_account_details
        self.on_server_details = on_server_details
        self.account_api = NextcloudApi()
        self.account_api.http.trust_invalid_certificates = bool(
            self.config.data.get("network", {}).get(
                "trust_invalid_certificates", False
            )
        )
        self._account_refresh_generation = 0
        self._closed = False
        self._building = True
        self._build_general()
        self._build_account()
        self._build_sync()
        self._build_network()
        self._build_advanced()
        account_details = cached_account_details(self.config)
        if account_details:
            self.set_account_details(account_details)
        server_details = cached_server_details(self.config)
        if server_details:
            self.set_server_details(server_details)
        self._building = False
        self._integration_unsubscribe = self.desktop_integration.subscribe(
            self._integration_changed
        )
        self._state_unsubscribe = self.runtime.state.subscribe(
            self._account_state_changed
        )
        self.connect("close-request", self._release_integration_subscription)

    def _build_account(self) -> None:
        account = self.config.data["account"]
        page = Adw.PreferencesPage(
            title=_("Account"),
            icon_name="avatar-default-symbolic",
        )
        self.account_page = page

        status = Adw.PreferencesGroup(title=_("Account Status"))
        self.account_status_row = Adw.ActionRow(
            title=_("Checking account status"),
            subtitle=_("Local account information is available below."),
            icon_name="dialog-information-symbolic",
        )
        status.add(self.account_status_row)
        page.add(status)

        identity = Adw.PreferencesGroup(title=_("Account Information"))
        identity.add(
            Adw.ActionRow(
                title=_("Username"),
                subtitle=account["login_name"],
                icon_name="avatar-default-symbolic",
            )
        )
        self.display_name_row = Adw.ActionRow(
            title=_("Display name"),
            subtitle=_("Not obtained yet"),
            icon_name="contact-new-symbolic",
        )
        identity.add(self.display_name_row)
        self.email_row = Adw.ActionRow(
            title=_("Email"),
            subtitle=_("Not obtained yet"),
            icon_name="mail-unread-symbolic",
        )
        identity.add(self.email_row)
        self.quota_row = Adw.ActionRow(
            title=_("Storage quota"),
            subtitle=_("Not obtained yet"),
            icon_name="drive-harddisk-symbolic",
        )
        identity.add(self.quota_row)
        recorded_authorization = account.get("authorization_name")
        authorization_subtitle = recorded_authorization or _(
            "Not recorded for this authorization; reconnect to use {name}"
        ).format(name=authorization_name())
        self.authorization_row = Adw.ActionRow(
            title=_("Authorization name in Nextcloud"),
            subtitle=authorization_subtitle,
            icon_name="computer-symbolic",
        )
        identity.add(self.authorization_row)
        identity.add(
            Adw.ActionRow(
                title=_("Local folder"),
                subtitle=account["local_root"],
                icon_name="folder-symbolic",
            )
        )
        page.add(identity)

        server = Adw.PreferencesGroup(title=_("Server Information"))
        server.add(
            Adw.ActionRow(
                title=_("Address"),
                subtitle=account["server_url"],
                icon_name="network-server-symbolic",
            )
        )
        self.server_software_row = Adw.ActionRow(
            title=_("Software"),
            subtitle=_("Not obtained yet"),
        )
        server.add(self.server_software_row)
        self.server_version_row = Adw.ActionRow(
            title=_("Version"),
            subtitle=_("Not obtained yet"),
        )
        server.add(self.server_version_row)
        self.server_status_row = Adw.ActionRow(
            title=_("Server status"),
            subtitle=_("Not obtained yet"),
        )
        server.add(self.server_status_row)
        page.add(server)

        actions = Adw.PreferencesGroup(title=_("Account Actions"))
        reconnect = Adw.ActionRow(
            title=_("Reconnect Account"),
            subtitle=_(
                "Renew authorization without changing the local folder or safety baseline."
            ),
            icon_name="view-refresh-symbolic",
            activatable=True,
        )
        reconnect.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        reconnect.connect(
            "activated", lambda _row: self.on_reconnect_account(self)
        )
        actions.add(reconnect)
        open_server = Adw.ActionRow(
            title=_("Open Nextcloud in Browser"),
            subtitle=account["server_url"],
            icon_name="web-browser-symbolic",
            activatable=True,
        )
        open_server.add_suffix(Gtk.Image.new_from_icon_name("external-link-symbolic"))
        open_server.connect(
            "activated",
            lambda _row: Gio.AppInfo.launch_default_for_uri(
                account["server_url"], None
            ),
        )
        actions.add(open_server)
        open_folder = Adw.ActionRow(
            title=_("Open Local Folder"),
            subtitle=account["local_root"],
            icon_name="folder-open-symbolic",
            activatable=True,
        )
        open_folder.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        open_folder.connect(
            "activated",
            lambda _row: Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(account["local_root"]).get_uri(), None
            ),
        )
        actions.add(open_folder)
        refresh = Adw.ActionRow(
            title=_("Refresh Account Information"),
            subtitle=_("Load current account and server details."),
            icon_name="view-refresh-symbolic",
            activatable=True,
        )
        refresh.connect("activated", lambda _row: self.refresh_account_details())
        actions.add(refresh)
        remove = Adw.ActionRow(
            title=_("Remove Account"),
            subtitle=_("Local files will not be deleted."),
            icon_name="user-trash-symbolic",
            activatable=True,
        )
        remove.add_css_class("error")
        remove.connect("activated", lambda _row: self._confirm_remove_account())
        actions.add(remove)
        page.add(actions)
        self.add(page)

    def show_account_page(self) -> None:
        self.set_visible_page(self.account_page)

    def _account_state_changed(self, snapshot: StateSnapshot) -> None:
        if snapshot.state == AppState.AUTH_REQUIRED:
            title = _("Authorization required")
            subtitle = _("Reconnect the account to resume synchronization.")
            icon = "dialog-password-symbolic"
        elif snapshot.state == AppState.KEYRING_LOCKED:
            title = _("Password keyring locked")
            subtitle = _("Unlock the password keyring to access the account.")
            icon = "changes-prevent-symbolic"
        elif snapshot.state == AppState.SYNCING:
            title = _("Connected and synchronizing")
            subtitle = snapshot.message or _("The account authorization is active.")
            icon = "emblem-synchronizing-symbolic"
        else:
            title = _("Account configured")
            subtitle = snapshot.message or _("The account is ready for synchronization.")
            icon = "emblem-ok-symbolic"
        self.account_status_row.set_title(title)
        self.account_status_row.set_subtitle(_(subtitle))
        self.account_status_row.set_icon_name(icon)

    def refresh_account_details(self) -> None:
        if self._closed:
            return
        self._account_refresh_generation += 1
        generation = self._account_refresh_generation
        account = self.config.data["account"]
        recorded_authorization = account.get("authorization_name")
        self.authorization_row.set_subtitle(
            recorded_authorization
            or _("Not recorded for this authorization; reconnect to use {name}").format(
                name=authorization_name()
            )
        )
        for row in (
            self.display_name_row,
            self.email_row,
            self.quota_row,
            self.server_software_row,
            self.server_version_row,
            self.server_status_row,
        ):
            row.set_subtitle(_("Loading…"))
        self.account_api.http.trust_invalid_certificates = bool(
            self.config.data.get("network", {}).get(
                "trust_invalid_certificates", False
            )
        )

        def server_ready(
            details: ServerDetails | None, error: Exception | None
        ) -> None:
            if self._closed or generation != self._account_refresh_generation:
                return
            if error or not details:
                unavailable = _("Unavailable")
                self.server_software_row.set_subtitle(unavailable)
                self.server_version_row.set_subtitle(unavailable)
                self.server_status_row.set_subtitle(
                    str(error or _("Could not read server information"))
                )
                return
            self.on_server_details(details)

        self.account_api.get_server_details(account["server_url"], server_ready)

        def account_ready(
            details: AccountDetails | None, error: Exception | None
        ) -> None:
            if self._closed or generation != self._account_refresh_generation:
                return
            if error or not details:
                if isinstance(error, PermissionError):
                    unavailable = _("Unavailable until the account is reconnected")
                    self.runtime.authentication_rejected()
                elif isinstance(error, NextcloudRateLimitError):
                    unavailable = _(
                        "Temporarily unavailable because Nextcloud limited requests. Refresh shortly."
                    )
                else:
                    unavailable = _("Could not load account information")
                    if error:
                        unavailable = f"{unavailable}: {error}"
                self.display_name_row.set_subtitle(unavailable)
                self.email_row.set_subtitle(unavailable)
                self.quota_row.set_subtitle(unavailable)
                return
            self.on_account_details(details)

        def credential_ready(
            password: str | None, error: Exception | None
        ) -> None:
            if self._closed or generation != self._account_refresh_generation:
                return
            if error or not password:
                if error:
                    unavailable = _("Could not access the stored credential")
                    unavailable = f"{unavailable}: {error}"
                else:
                    unavailable = _("Unavailable until the account is reconnected")
                self.display_name_row.set_subtitle(unavailable)
                self.email_row.set_subtitle(unavailable)
                self.quota_row.set_subtitle(unavailable)
                return
            self.runtime.logger.add_secret(password)
            self.account_api.get_account_details(
                account["server_url"],
                account["login_name"],
                password,
                account_ready,
            )

        self.credentials.lookup(
            account["server_url"], account["login_name"], credential_ready
        )

    def set_account_details(self, details: AccountDetails) -> None:
        self.display_name_row.set_subtitle(details.display_name)
        self.email_row.set_subtitle(details.email or _("Not provided"))
        self.set_storage_usage(details.quota_used, details.quota_total)

    def set_storage_usage(self, used_bytes: int | None, total_bytes: int | None) -> None:
        if used_bytes is None:
            self.quota_row.set_subtitle(_("Not reported"))
            return
        used = GLib.format_size(max(0, used_bytes))
        if total_bytes is not None and total_bytes > 0:
            self.quota_row.set_subtitle(
                _("{used} of {total} used").format(
                    used=used,
                    total=GLib.format_size(total_bytes),
                )
            )
            return
        self.quota_row.set_subtitle(
            _("{used} used · Unlimited or server-defined quota").format(
                used=used
            )
        )

    def set_server_details(self, details: ServerDetails) -> None:
        self.server_software_row.set_subtitle(details.product_name)
        self.server_version_row.set_subtitle(details.version or _("Not reported"))
        if details.maintenance:
            status = _("Maintenance mode")
        elif details.needs_database_upgrade:
            status = _("Database upgrade required")
        else:
            status = _("Available")
        self.server_status_row.set_subtitle(status)

    def _build_general(self) -> None:
        page = Adw.PreferencesPage(title=_("General"), icon_name="preferences-system-symbolic")
        startup = Adw.PreferencesGroup(title=_("Startup"))
        self.autostart = Adw.SwitchRow(
            title=_("Start PyNextCloud Sync when I sign in"),
            active=self.config.data["general"]["autostart"],
        )
        self.autostart.connect("notify::active", self._save_general)
        startup.add(self.autostart)
        page.add(startup)
        power = Adw.PreferencesGroup(title=_("Power"))
        self.pause_battery = Adw.SwitchRow(
            title=_("Pause synchronization while on battery"),
            subtitle=_("A running synchronization is allowed to finish."),
            active=self.config.data["general"]["pause_on_battery"],
        )
        self.pause_battery.connect("notify::active", self._save_general)
        power.add(self.pause_battery)
        page.add(power)
        folder = Adw.PreferencesGroup(title=_("Local Folder"))
        account = self.config.data["account"]
        folder.add(
            Adw.ActionRow(
                title=_("NextCloud folder"),
                subtitle=account["local_root"],
                icon_name="folder-symbolic",
            )
        )
        integration_state = self.desktop_integration.state
        self.nautilus_bookmark = Adw.SwitchRow(
            title=_("Show in Files sidebar"),
            subtitle=_("Adds the synchronized folder to the file manager sidebar."),
            active=integration_state.nautilus_bookmark,
        )
        self.nautilus_bookmark.connect(
            "notify::active", self._toggle_nautilus_bookmark
        )
        folder.add(self.nautilus_bookmark)
        self.desktop_shortcut = Adw.SwitchRow(
            title=_("Show on Desktop"),
            subtitle=_("Creates a link to the synchronized folder on the desktop."),
            active=integration_state.desktop_shortcut,
        )
        self.desktop_shortcut.connect(
            "notify::active", self._toggle_desktop_shortcut
        )
        folder.add(self.desktop_shortcut)
        self.special_folder_icon = Adw.SwitchRow(
            title=_("Use special folder icon"),
            subtitle=_("Identifies the synchronized folder and its shortcuts in Files."),
            active=integration_state.special_icon,
        )
        self.special_folder_icon.connect(
            "notify::active", self._toggle_special_folder_icon
        )
        folder.add(self.special_folder_icon)
        page.add(folder)
        self.add(page)

    def _toggle_nautilus_bookmark(self, *_args: object) -> None:
        if self._building:
            return
        self.desktop_integration.set_nautilus_bookmark(
            self.nautilus_bookmark.get_active()
        )
        self._integration_changed(self.desktop_integration.state)

    def _toggle_desktop_shortcut(self, *_args: object) -> None:
        if self._building:
            return
        self.desktop_integration.set_desktop_shortcut(
            self.desktop_shortcut.get_active()
        )
        self._integration_changed(self.desktop_integration.state)

    def _toggle_special_folder_icon(self, *_args: object) -> None:
        if self._building:
            return
        self.desktop_integration.set_special_icon(
            self.special_folder_icon.get_active()
        )
        self._integration_changed(self.desktop_integration.state)

    def _integration_changed(self, state: object) -> None:
        self._building = True
        try:
            self.nautilus_bookmark.set_active(state.nautilus_bookmark)
            self.desktop_shortcut.set_active(state.desktop_shortcut)
            self.special_folder_icon.set_active(state.special_icon)
        finally:
            self._building = False

    def _release_integration_subscription(self, *_args: object) -> bool:
        self._closed = True
        self._account_refresh_generation += 1
        if self._integration_unsubscribe:
            self._integration_unsubscribe()
            self._integration_unsubscribe = None
        if self._state_unsubscribe:
            self._state_unsubscribe()
            self._state_unsubscribe = None
        return False

    def _build_sync(self) -> None:
        sync = self.config.data["sync"]
        page = Adw.PreferencesPage(title=_("Synchronization"), icon_name="emblem-synchronizing-symbolic")
        manual_group = Adw.PreferencesGroup()
        self.manual_banner = Adw.Banner(
            title=_("Automatic synchronization is off. Files synchronize only with Sync Now."),
            revealed=manual_only(sync),
        )
        manual_group.add(self.manual_banner)
        page.add(manual_group)

        local = Adw.PreferencesGroup(title=_("Local Changes"))
        self.inotify = Adw.SwitchRow(
            title=_("Monitor filesystem changes"),
            subtitle=_("Synchronizes shortly after a local file changes."),
            active=sync["local_inotify_enabled"],
        )
        self.local_timer = Adw.SwitchRow(
            title=_("Run a local safety interval"), active=sync["local_interval_enabled"]
        )
        self.local_minutes = _spin_row(
            _("Local interval (minutes)"), 1, 1440, sync["local_interval_minutes"]
        )
        self.local_minutes.set_visible(self.local_timer.get_active())
        for row in (self.inotify, self.local_timer):
            row.connect("notify::active", self._save_sync)
        self.local_minutes.connect("notify::value", self._save_sync)
        local.add(self.inotify)
        local.add(self.local_timer)
        local.add(self.local_minutes)
        page.add(local)

        remote = Adw.PreferencesGroup(title=_("Remote Changes"))
        self.push = Adw.SwitchRow(
            title=_("Use server push notifications"),
            subtitle=_("Near-real-time detection when notify_push is supported."),
            active=sync["remote_push_enabled"],
        )
        self.remote_timer = Adw.SwitchRow(
            title=_("Run a remote safety interval"),
            subtitle=_("Recommended because push delivery is best effort."),
            active=sync["remote_interval_enabled"],
        )
        self.remote_minutes = _spin_row(
            _("Remote interval (minutes)"), 1, 1440, sync["remote_interval_minutes"]
        )
        self.remote_minutes.set_visible(self.remote_timer.get_active())
        for row in (self.push, self.remote_timer):
            row.connect("notify::active", self._save_sync)
        self.remote_minutes.connect("notify::value", self._save_sync)
        remote.add(self.push)
        remote.add(self.remote_timer)
        remote.add(self.remote_minutes)
        self.push_status = Adw.ActionRow(
            title=_("Push connection"), subtitle=self.runtime.push_message or _("Not connected")
        )
        remote.add(self.push_status)
        page.add(remote)

        excluded = Adw.PreferencesGroup(title=_("Excluded Files"))
        self.exclusions_enabled = Adw.SwitchRow(
            title=_("Exclude disposable files"),
            subtitle=_("Hidden files remain synchronized unless a rule matches."),
            active=sync["exclude_patterns_enabled"],
        )
        self.exclusions_enabled.connect("notify::active", self._save_sync)
        excluded.add(self.exclusions_enabled)
        edit_row = Adw.ActionRow(
            title=_("File patterns"),
            subtitle=_("Names, extensions, and wildcard patterns"),
            activatable=True,
        )
        edit_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        edit_row.connect("activated", self._show_exclusions)
        excluded.add(edit_row)
        page.add(excluded)

        reliability = Adw.PreferencesGroup(title=_("Reliability"))
        self.retries = _spin_row(_("Maximum sync retries"), 1, 10, sync["max_sync_retries"])
        self.retries.connect("notify::value", self._save_sync)
        reliability.add(self.retries)
        page.add(reliability)
        self.add(page)

    def _build_network(self) -> None:
        page = Adw.PreferencesPage(title=_("Network"), icon_name="network-wired-symbolic")
        proxy = Adw.PreferencesGroup(title=_("Proxy"))
        self.proxy = Adw.EntryRow(title=_("Custom HTTP proxy"))
        self.proxy.set_text(self.config.data["network"].get("custom_proxy") or "")
        self.proxy.set_show_apply_button(True)
        self.proxy.connect("apply", self._save_network)
        proxy.add(self.proxy)
        page.add(proxy)
        tls = Adw.PreferencesGroup(title=_("TLS"))
        self.trust = Adw.SwitchRow(
            title=_("Allow invalid or self-signed certificates"),
            subtitle=_("This weakens connection security. Enable only for a server you trust."),
            active=self.config.data["network"]["trust_invalid_certificates"],
        )
        self.trust.connect("notify::active", self._save_network)
        tls.add(self.trust)
        page.add(tls)
        self.add(page)

    def _build_advanced(self) -> None:
        page = Adw.PreferencesPage(title=_("Advanced"), icon_name="applications-system-symbolic")
        group = Adw.PreferencesGroup(title=_("Logging"))
        logging_config = self.config.data["logging"]
        self.save_logs = Adw.SwitchRow(
            title=_("Save log files"),
            subtitle=_("Live activity remains available when file logging is off."),
            active=logging_config["save_logs"],
        )
        self.save_logs.connect("notify::active", self._save_logging)
        group.add(self.save_logs)
        self.log_retention = _spin_row(
            _("Keep daily logs (days)"), 1, 365, logging_config["retention_days"]
        )
        self.log_retention.set_sensitive(self.save_logs.get_active())
        self.log_retention.connect("notify::value", self._save_logging)
        group.add(self.log_retention)
        log_folder = Adw.ActionRow(
            title=_("Log folder"),
            subtitle=str(self.runtime.logger.directory),
            icon_name="folder-symbolic",
            activatable=True,
        )
        log_folder.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        log_folder.connect("activated", self._open_log_folder)
        group.add(log_folder)
        group.add(
            Adw.ActionRow(
                title=_("Daily file naming"),
                subtitle="pynextcloud-sync-YYYY-MM-DD.log",
                icon_name="text-x-generic-symbolic",
            )
        )
        self.detailed = Adw.SwitchRow(
            title=_("Detailed synchronization output"),
            active=self.config.data["sync"]["detailed_output"],
        )
        self.detailed.connect("notify::active", self._save_sync)
        group.add(self.detailed)
        page.add(group)
        safety_config = self.config.data["safety"]
        safety = Adw.PreferencesGroup(
            title=_("Deletion Safety Guard"),
            description=_(
                "Synchronization is blocked before nextcloudcmd starts when too many previously synchronized local files disappear."
            ),
        )
        self.deletion_count = _spin_row(
            _("Review after this many missing files"),
            1,
            100_000,
            safety_config["deletion_count_threshold"],
        )
        self.deletion_percent = _spin_row(
            _("Review after this percentage is missing"),
            1,
            100,
            safety_config["deletion_percent_threshold"],
        )
        self.deletion_count.connect("notify::value", self._save_safety)
        self.deletion_percent.connect("notify::value", self._save_safety)
        safety.add(self.deletion_count)
        safety.add(self.deletion_percent)
        safety.add(
            Adw.ActionRow(
                title=_("Empty, missing, replaced, or unreadable folder"),
                subtitle=_("Always requires a safety review regardless of the limits above."),
                icon_name="security-high-symbolic",
            )
        )
        page.add(safety)
        diagnostics = Adw.PreferencesGroup(title=_("Diagnostics"))
        diagnostics.add(
            Adw.ActionRow(
                title=_("inotify watches"), subtitle=str(self.runtime.watched_directories)
            )
        )
        diagnostics.add(
            Adw.ActionRow(title=_("notify_push"), subtitle=self.runtime.push_state.value)
        )
        last_code = self.config.data["runtime"].get("last_exit_code")
        diagnostics.add(
            Adw.ActionRow(title=_("Last exit code"), subtitle=str(last_code) if last_code is not None else _("None"))
        )
        page.add(diagnostics)
        self.add(page)

    def _save_general(self, *_args: object) -> None:
        if self._building:
            return
        general = self.config.data["general"]
        general["autostart"] = self.autostart.get_active()
        general["pause_on_battery"] = self.pause_battery.get_active()
        self.config.save()
        AutostartManager().set_enabled(general["autostart"])

    def _save_sync(self, *_args: object) -> None:
        if self._building:
            return
        self.local_minutes.set_visible(self.local_timer.get_active())
        self.remote_minutes.set_visible(self.remote_timer.get_active())
        sync = self.config.data["sync"]
        sync.update(
            {
                "local_inotify_enabled": self.inotify.get_active(),
                "local_interval_enabled": self.local_timer.get_active(),
                "local_interval_minutes": int(self.local_minutes.get_value()),
                "remote_push_enabled": self.push.get_active(),
                "remote_interval_enabled": self.remote_timer.get_active(),
                "remote_interval_minutes": int(self.remote_minutes.get_value()),
                "exclude_patterns_enabled": self.exclusions_enabled.get_active(),
                "max_sync_retries": int(self.retries.get_value()),
                "detailed_output": self.detailed.get_active() if hasattr(self, "detailed") else sync["detailed_output"],
            }
        )
        self.config.save()
        self.manual_banner.set_revealed(manual_only(sync))

    def _save_logging(self, *_args: object) -> None:
        if self._building:
            return
        enabled = self.save_logs.get_active()
        retention = int(self.log_retention.get_value())
        self.log_retention.set_sensitive(enabled)
        logging_config = self.config.data["logging"]
        logging_config["save_logs"] = enabled
        logging_config["retention_days"] = retention
        self.config.save()
        self.runtime.logger.configure(
            save_to_disk=enabled,
            retention_days=retention,
        )

    def _save_safety(self, *_args: object) -> None:
        if self._building:
            return
        safety = self.config.data["safety"]
        safety["deletion_count_threshold"] = int(self.deletion_count.get_value())
        safety["deletion_percent_threshold"] = int(
            self.deletion_percent.get_value()
        )
        self.config.save()

    def _open_log_folder(self, _row: Adw.ActionRow) -> None:
        self.runtime.logger.directory.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(self.runtime.logger.directory.as_uri(), None)

    def _save_network(self, *_args: object) -> None:
        if self._building:
            return
        previous = dict(self.config.data["network"])
        value = self.proxy.get_text().strip()
        self.config.data["network"]["custom_proxy"] = value or None
        self.config.data["network"]["trust_invalid_certificates"] = self.trust.get_active()
        try:
            self.config.save()
            self.proxy.set_title(_("Custom HTTP proxy"))
            self.proxy.remove_css_class("error")
        except ConfigurationError:
            self.config.data["network"] = previous
            self.proxy.set_title(_("Invalid HTTP proxy URL"))
            self.proxy.add_css_class("error")

    def _show_exclusions(self, _row: Adw.ActionRow) -> None:
        dialog = ExclusionsDialog(self.config, self.runtime.reconfigure)
        dialog.present(self)

    def _confirm_remove_account(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Remove Nextcloud Account?"),
            body=_("The account credential will be removed from the password keyring. Your local NextCloud folder and all files inside it will remain untouched."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove Account"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(self, None, self._remove_account_choice)

    def _remove_account_choice(
        self, dialog: Adw.AlertDialog, result: Gio.AsyncResult
    ) -> None:
        if dialog.choose_finish(result) == "remove":
            self.on_remove_account()
