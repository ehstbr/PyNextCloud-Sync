from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from pynextcloud_sync import APP_ID
from pynextcloud_sync.core.desktop_integration import DesktopIntegration
from pynextcloud_sync.core.runtime import RuntimeController
from pynextcloud_sync.core.updates import (
    UpdateCheckResult,
    UpdateChecker,
    UpdateManifest,
)
from pynextcloud_sync.core.window_presentation import MappedWindowPresenter
from pynextcloud_sync.nextcloud.credentials import CredentialStore
from pynextcloud_sync.nextcloud.api import AccountDetails, NextcloudApi, ServerDetails
from pynextcloud_sync.storage.config import ConfigStore, ConfigurationError
from pynextcloud_sync.storage.log import AppLogger
from pynextcloud_sync.storage.remote_details import (
    store_account_details,
    store_server_details,
    store_storage_usage,
)
from pynextcloud_sync.ui.main_window import MainWindow
from pynextcloud_sync.ui.reconnect import ReconnectWindow
from pynextcloud_sync.ui.bootstrap import BootstrapWindow
from pynextcloud_sync.ui.settings import SettingsWindow
from pynextcloud_sync.ui.setup import SetupWindow
from pynextcloud_sync.ui.tray import StatusNotifier
from pynextcloud_sync.ui.update_window import UpdateWindow
from pynextcloud_sync.util.i18n import _
from pynextcloud_sync.util.paths import project_root


class PyNextCloudApplication(Adw.Application):
    def __init__(self, background: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.background = background
        self._activation_count = 0
        self._startup_update_complete = False
        self._startup_update_in_progress = False
        self._pending_activation_show_main = False
        self._manual_update_in_progress = False
        self._mandatory_update_manifest: UpdateManifest | None = None
        self.config = ConfigStore()
        self.logger = AppLogger()
        self.credentials = CredentialStore(logger=self.logger)
        self.update_checker = UpdateChecker()
        self.runtime: RuntimeController | None = None
        self.desktop_integration: DesktopIntegration | None = None
        self.main_window: MainWindow | None = None
        self.bootstrap_window: BootstrapWindow | None = None
        self.settings_window: SettingsWindow | None = None
        self.reconnect_window: ReconnectWindow | None = None
        self.setup_window: SetupWindow | None = None
        self.update_window: UpdateWindow | None = None
        self.tray: StatusNotifier | None = None
        self._update_window_presenter = MappedWindowPresenter(
            idle_add=GLib.idle_add,
            show=lambda manifest, parent: self._show_update_window(
                manifest,
                parent=parent,
            ),
            source_remove=GLib.SOURCE_REMOVE,
        )
        self._safety_dialog_presenter = MappedWindowPresenter(
            idle_add=GLib.idle_add,
            show=self._show_queued_safety_review,
            source_remove=GLib.SOURCE_REMOVE,
        )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.hold()
        try:
            self.config.load()
        except ConfigurationError as exc:
            self.logger.error(exc)
            self.config.data["account"] = None
        logging_config = self.config.data["logging"]
        self.logger.configure(
            save_to_disk=logging_config["save_logs"],
            retention_days=logging_config["retention_days"],
        )
        self._install_actions()

    def _install_actions(self) -> None:
        for name, callback in (
            ("show", lambda *_args: self.present_main()),
            ("sync", lambda *_args: self._tray_sync()),
            ("log", lambda *_args: self.show_log()),
            ("settings", lambda *_args: self.show_settings()),
            ("review-safety", self._review_safety_from_notification),
            (
                "check-update",
                lambda *_args: self.check_for_updates(self.get_active_window()),
            ),
            ("quit", lambda *_args: self.request_quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def do_activate(self) -> None:
        first_activation = self._activation_count == 0
        self._activation_count += 1
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            theme.add_search_path(str(project_root() / "data" / "icons"))
            theme.add_search_path(str(project_root() / "data" / "icons" / "status"))
        show_main = not (first_activation and self.background)
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if not self._startup_update_complete:
            self._pending_activation_show_main |= show_main
            self._begin_startup_update_check()
            return
        self._continue_activation(show_main=show_main)

    def _begin_startup_update_check(self) -> None:
        if self._startup_update_in_progress:
            return
        self._startup_update_in_progress = True
        try:
            self.update_checker.check(self._startup_update_finished)
        except Exception as exc:
            self._startup_update_finished(UpdateCheckResult(error=str(exc)))

    def _startup_update_finished(self, result: UpdateCheckResult) -> None:
        self._startup_update_in_progress = False
        self._startup_update_complete = True
        show_main = self._pending_activation_show_main
        self._pending_activation_show_main = False
        if result.error:
            self.logger.warning("Automatic update check failed: %s", result.error)
            self._continue_activation(show_main=show_main)
            return
        if result.update_available and result.latest and result.latest.mandatory:
            self._enter_mandatory_update_mode(result.latest)
            return
        self._continue_activation(show_main=show_main)
        if result.update_available and result.latest:
            if show_main:
                self._queue_update_window_for_mapped_parent(result.latest)
            else:
                self._show_update_window(result.latest)

    def _continue_activation(self, *, show_main: bool) -> None:
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if not self.config.configured:
            if not self.setup_window:
                self.setup_window = SetupWindow(
                    self, self.config, self.credentials, self._setup_complete
                )
            self.setup_window.present()
            return
        if not self.config.data.get("safety", {}).get("bootstrap_complete", False):
            self._ensure_bootstrap()
            return
        self._ensure_desktop_integration()
        self._ensure_runtime()
        self._ensure_tray()
        if show_main:
            self.present_main()

    def check_for_updates(self, parent: Gtk.Window | None = None) -> None:
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if self._manual_update_in_progress:
            return
        self._manual_update_in_progress = True
        progress = Adw.AlertDialog(
            heading=_("Checking for Updates"),
            body=_("Contacting the GitHub version service…"),
        )
        progress.present(parent)

        def finished(result: UpdateCheckResult) -> None:
            self._manual_update_in_progress = False
            progress.close()
            if result.error:
                self.logger.warning("Manual update check failed: %s", result.error)
                self._show_status_dialog(
                    _("Could Not Check for Updates"),
                    _(
                        "The version information could not be obtained. Check your "
                        "connection and try again later."
                    ),
                    parent,
                )
                return
            if result.update_available and result.latest:
                if result.latest.mandatory:
                    self._enter_mandatory_update_mode(result.latest)
                else:
                    self._show_update_window(result.latest, parent=parent)
                return
            self._show_status_dialog(
                _("PyNextCloud Sync Is Up to Date"),
                _("You are already using the latest available version."),
                parent,
            )

        try:
            self.update_checker.check(finished)
        except Exception as exc:
            finished(UpdateCheckResult(error=str(exc)))

    def _show_status_dialog(
        self,
        heading: str,
        body: str,
        parent: Gtk.Window | None,
    ) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", _("Close"))
        dialog.set_default_response("close")

        def chosen(source: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
            source.choose_finish(result)

        dialog.choose(parent, None, chosen)

    def _show_update_window(
        self,
        manifest: UpdateManifest,
        *,
        parent: Gtk.Window | None = None,
    ) -> None:
        if parent is None:
            parent = self._update_window_parent(require_mapped=True)
        elif not parent.get_mapped():
            parent = None
        if self.update_window:
            same_manifest = self.update_window.manifest == manifest
            same_parent = self.update_window.get_transient_for() is parent
            if same_manifest and same_parent:
                self._present_update_window_foreground(self.update_window)
                return
            if self.update_window.mandatory:
                self._present_update_window_foreground(self.update_window)
                return
            old_window = self.update_window
            self.update_window = None
            old_window.close()
        self.update_window = UpdateWindow(
            self,
            manifest,
            parent=parent,
            on_close=self._update_window_closed,
            on_quit=self.quit,
        )
        self.update_window.present()
        GLib.idle_add(self._present_update_window_foreground, self.update_window)

    def _update_window_parent(self, *, require_mapped: bool = False) -> Gtk.Window | None:
        candidates = (
            self.get_active_window(),
            self.main_window,
            self.bootstrap_window,
            self.setup_window,
            self.settings_window,
        )
        for candidate in candidates:
            if (
                candidate
                and candidate is not self.update_window
                and candidate.get_visible()
                and (not require_mapped or candidate.get_mapped())
            ):
                return candidate
        return None

    def _queue_update_window_for_mapped_parent(
        self,
        manifest: UpdateManifest,
        parent: Gtk.Window | None = None,
    ) -> None:
        self._update_window_presenter.clear()
        parent = parent or self._update_window_parent()
        if not parent:
            self._show_update_window(manifest)
            return
        self._update_window_presenter.queue(manifest, parent)

    def _present_update_window_foreground(self, window: UpdateWindow) -> bool:
        if self.update_window is not window:
            return GLib.SOURCE_REMOVE
        window.unminimize()
        window.present()
        return GLib.SOURCE_REMOVE

    def _update_window_closed(self, window: UpdateWindow) -> None:
        if self.update_window is window:
            self.update_window = None

    def _enter_mandatory_update_mode(self, manifest: UpdateManifest) -> None:
        self._mandatory_update_manifest = manifest
        if self.tray:
            self.tray.stop()
            self.tray = None
        if self.runtime:
            self.runtime.stop()
            self.runtime = None
        if self.settings_window:
            self.settings_window.close()
            self.settings_window = None
        if self.main_window:
            old_window = self.main_window
            self.main_window = None
            old_window.dispose_for_account_reset()
            old_window.close()
        self._show_update_window(manifest)

    def _setup_complete(self) -> None:
        if self.setup_window:
            old_setup = self.setup_window
            old_setup.set_visible(False)
            self.remove_window(old_setup)
            self.setup_window = None
        self._ensure_bootstrap(initialize_integrations=True)

    def _ensure_bootstrap(
        self,
        *,
        recovery: bool = False,
        initialize_integrations: bool = False,
    ) -> None:
        if self.bootstrap_window:
            self.bootstrap_window.present()
            return
        self._bootstrap_initialize_integrations = initialize_integrations
        self.bootstrap_window = BootstrapWindow(
            self,
            self.config,
            self.credentials,
            self.logger,
            self._bootstrap_complete,
            self._bootstrap_reconnect_account,
            recovery=recovery,
        )
        self.bootstrap_window.present()

    def _bootstrap_complete(self) -> None:
        if self.bootstrap_window:
            old_bootstrap = self.bootstrap_window
            self.bootstrap_window = None
            old_bootstrap.completed = True
            old_bootstrap.close()
            self.remove_window(old_bootstrap)
        self._ensure_desktop_integration()
        if self.desktop_integration and getattr(
            self, "_bootstrap_initialize_integrations", False
        ):
            results = self.desktop_integration.initialize_defaults()
            failed = [name for name, succeeded in results.items() if not succeeded]
            if failed:
                self.logger.warning(
                    "Could not initialize desktop integrations: %s", ", ".join(failed)
                )
        self._ensure_runtime()
        self._ensure_tray()
        self.present_main()
        self._bootstrap_initialize_integrations = False

    def _bootstrap_reconnect_account(self) -> None:
        if self.bootstrap_window:
            old_bootstrap = self.bootstrap_window
            self.bootstrap_window = None
            old_bootstrap.completed = True
            old_bootstrap.runner.cancel()
            old_bootstrap.runner.cleanup(old_bootstrap.analysis)
            old_bootstrap.close()
            self.remove_window(old_bootstrap)
        self.reconnect_account()

    def _ensure_runtime(self) -> None:
        if self._mandatory_update_manifest or self.runtime or not self.config.data.get("safety", {}).get(
            "bootstrap_complete", False
        ):
            return
        self.runtime = RuntimeController(
            self.config,
            self.credentials,
            self.logger,
            self._notify_sync_failure,
            self._notify_safety_alert,
            self._account_details_updated,
            self._server_details_updated,
            self._storage_usage_updated,
        )
        # A notification can outlive a previous application process. Clear any
        # stale review before the new runtime performs its own safety check.
        self.withdraw_notification("safety-review")
        self.runtime.start()

    def _ensure_desktop_integration(self) -> None:
        account = self.config.data.get("account")
        if not account:
            return
        root = Path(account["local_root"])
        if (
            self.desktop_integration
            and self.desktop_integration.sync_root != root.expanduser().absolute()
        ):
            self.desktop_integration.close()
            self.desktop_integration = None
        if not self.desktop_integration:
            self.desktop_integration = DesktopIntegration(root)

    def _ensure_tray(self) -> None:
        if self.tray or not self.runtime:
            return
        self.tray = StatusNotifier(
            self.runtime.state,
            self.present_main,
            self._tray_sync,
            lambda: self.runtime.set_paused(not self.runtime.scheduler.user_paused),
            self.open_folder,
            self.show_log,
            self.show_settings,
            self.request_quit,
            self.logger,
        )
        self.tray.start()

    def _tray_sync(self) -> None:
        if self.runtime and self.runtime.scheduler.safety_alert:
            self.present_main()
            self.review_safety_alert(self.main_window)
            return
        if self.runtime and self.runtime.scheduler.authentication_required:
            self.show_settings("account")
            return
        if self.runtime:
            self.runtime.sync_now()

    def _ensure_main_window(self) -> None:
        if self.main_window or not self.runtime:
            return
        self.main_window = MainWindow(self, self.config, self.runtime, self.logger)

    def present_main(self) -> None:
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if not self.config.configured:
            self.activate()
            return
        if not self.config.data.get("safety", {}).get("bootstrap_complete", False):
            self._ensure_bootstrap()
            return
        self._ensure_runtime()
        self._ensure_tray()
        self._ensure_main_window()
        if self.main_window:
            self.main_window.unminimize()
            self.main_window.present()
            if self.update_window:
                self._queue_update_window_for_mapped_parent(
                    self.update_window.manifest,
                    self.main_window,
                )

    def open_folder(self) -> None:
        account = self.config.data.get("account")
        if not account:
            return
        root = Path(account["local_root"])
        root.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(root.as_uri(), None)

    def show_log(self) -> None:
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if not self.config.configured:
            self.activate()
            return
        if not self.config.data.get("safety", {}).get("bootstrap_complete", False):
            self._ensure_bootstrap()
            return
        self._ensure_runtime()
        self._ensure_tray()
        self._ensure_main_window()
        if self.main_window:
            self.main_window.show_log()

    def show_settings(self, page: str | None = None) -> None:
        if self._mandatory_update_manifest:
            self._show_update_window(self._mandatory_update_manifest)
            return
        if not self.config.configured:
            self.activate()
            return
        if not self.config.data.get("safety", {}).get("bootstrap_complete", False):
            self._ensure_bootstrap()
            return
        self._ensure_runtime()
        self._ensure_tray()
        self._ensure_desktop_integration()
        if not self.runtime or not self.desktop_integration:
            return
        if not self.settings_window:
            self.settings_window = SettingsWindow(
                self,
                self.config,
                self.runtime,
                self.desktop_integration,
                self.reconnect_account,
                self.remove_account,
                self._account_details_updated,
                self._server_details_updated,
            )
            self.settings_window.connect("close-request", self._settings_window_closed)
        self.settings_window.unminimize()
        self.settings_window.present()
        if page == "account":
            self.settings_window.show_account_page()

    def reconnect_account(self, parent: Gtk.Window | None = None) -> None:
        if self._mandatory_update_manifest or not self.config.configured:
            return
        if self.reconnect_window:
            self.reconnect_window.unminimize()
            self.reconnect_window.present()
            return
        parent = parent or self.settings_window or self.main_window
        self.reconnect_window = ReconnectWindow(
            self,
            self.config,
            self.credentials,
            self.logger,
            self._reconnect_complete,
            self._reconnect_closed,
            parent=parent,
        )
        self.reconnect_window.present()

    def _reconnect_complete(self, account_details: AccountDetails) -> None:
        self.withdraw_notification("auth-failure")
        self._account_details_updated(account_details)
        if self.runtime:
            self.runtime.authentication_restored()
        elif not self.config.data.get("safety", {}).get(
            "bootstrap_complete", False
        ):
            self._ensure_bootstrap()

    def _account_details_updated(self, details: AccountDetails) -> None:
        try:
            store_account_details(self.config, details)
        except Exception as exc:
            self.logger.warning("Could not persist account details: %s", exc)
        if self.settings_window:
            self.settings_window.set_account_details(details)
        if self.main_window:
            self.main_window.set_account_details(details)

    def _server_details_updated(self, details: ServerDetails) -> None:
        try:
            store_server_details(self.config, details)
        except Exception as exc:
            self.logger.warning("Could not persist server details: %s", exc)
        if self.settings_window:
            self.settings_window.set_server_details(details)

    def _storage_usage_updated(
        self, used: int | None, total: int | None
    ) -> None:
        try:
            store_storage_usage(self.config, used, total)
        except Exception as exc:
            self.logger.warning("Could not persist storage usage: %s", exc)
        if self.settings_window:
            self.settings_window.set_storage_usage(used, total)
        if self.main_window:
            self.main_window.set_storage_usage(used, total)

    def _reconnect_closed(self, window: ReconnectWindow) -> None:
        if self.reconnect_window is window:
            self.reconnect_window = None

    def _settings_window_closed(self, window: SettingsWindow) -> bool:
        if self.settings_window is window:
            self.settings_window = None
        return False

    def main_window_closed(self, window: MainWindow) -> None:
        if self.main_window is window:
            self.main_window = None

    def _notify_sync_failure(self, result: object) -> None:
        if getattr(result, "classification", "") == "authentication":
            notification = Gio.Notification.new(_("Nextcloud account needs attention"))
            notification.set_body(_("Open PyNextCloud Sync to check the account credential."))
            notification.set_default_action("app.show")
            self.send_notification("auth-failure", notification)
        else:
            notification = Gio.Notification.new(_("Synchronization failed"))
            retries = self.config.data["sync"]["max_sync_retries"]
            notification.set_body(
                _("Synchronization failed after {retries} retries. Open the log for details.").format(
                    retries=retries
                )
            )
            notification.set_default_action("app.log")
            self.send_notification("sync-failure", notification)

    def _notify_safety_alert(self, alert: object) -> None:
        notification = Gio.Notification.new(_("Synchronization paused for safety"))
        notification.set_priority(Gio.NotificationPriority.URGENT)
        count = int(getattr(alert, "missing_count", 0))
        if count:
            notification.set_body(
                _("Local files are missing ({count}). Review the change before they can be deleted from Nextcloud.").format(
                    count=count
                )
            )
        else:
            notification.set_body(
                _("The local synchronization folder changed unexpectedly. Nothing was deleted from Nextcloud.")
            )
        notification.set_default_action("app.review-safety")
        notification.add_button(_("Review Now"), "app.review-safety")
        self.send_notification("safety-review", notification)

    def _review_safety_from_notification(self, *_args: object) -> None:
        self.present_main()
        if (
            self.runtime
            and self.runtime.scheduler.safety_alert
            and self.main_window
        ):
            self._safety_dialog_presenter.queue(
                self.runtime.scheduler.safety_alert,
                self.main_window,
            )
        else:
            self.withdraw_notification("safety-review")

    def _show_queued_safety_review(
        self, expected_alert: object, parent: Gtk.Window
    ) -> None:
        if (
            self.runtime
            and self.runtime.scheduler.safety_alert is expected_alert
        ):
            self.review_safety_alert(parent)
        else:
            self.withdraw_notification("safety-review")

    def review_safety_alert(self, parent: Gtk.Window | None = None) -> None:
        if not self.runtime or not self.runtime.scheduler.safety_alert:
            return
        alert = self.runtime.scheduler.safety_alert
        examples = "\n".join(f"• {path}" for path in alert.missing_paths[:8])
        body = _(alert.message)
        if examples:
            body += "\n\n" + examples
        dialog = Adw.AlertDialog(
            heading=_("Synchronization blocked for safety"),
            body=body,
        )
        dialog.add_response("cancel", _("Keep Paused"))
        dialog.add_response("restore", _("Restore from Nextcloud"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.SUGGESTED)
        if alert.can_approve_once:
            dialog.add_response("approve", _("Approve These Deletions Once"))
            dialog.set_response_appearance("approve", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(parent, None, self._safety_choice)

    def _safety_choice(self, dialog: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
        response = dialog.choose_finish(result)
        if response == "approve" and self.runtime:
            self._safety_dialog_presenter.clear()
            self.withdraw_notification("safety-review")
            self.runtime.approve_safety_once()
        elif response == "restore":
            self._safety_dialog_presenter.clear()
            self.withdraw_notification("safety-review")
            self._start_safety_recovery()

    def _start_safety_recovery(self) -> None:
        if self.settings_window:
            self.settings_window.close()
            self.settings_window = None
        if self.tray:
            self.tray.stop()
            self.tray = None
        if self.runtime:
            self.runtime.stop()
            self.runtime = None
        if self.main_window:
            old_window = self.main_window
            self.main_window = None
            old_window.dispose_for_account_reset()
            old_window.close()
        self.config.data["safety"]["bootstrap_complete"] = False
        self.config.save()
        self._ensure_bootstrap(recovery=True, initialize_integrations=False)

    def request_quit(self) -> None:
        if self.runtime and self.runtime.engine.running:
            notification = Gio.Notification.new(_("Finishing synchronization"))
            notification.set_body(
                _("PyNextCloud Sync will quit when the current synchronization finishes.")
            )
            self.send_notification("quit-pending", notification)
            GLib.timeout_add_seconds(1, self._quit_when_ready)
            return
        self.quit()

    def remove_account(self) -> None:
        account = self.config.data.get("account")
        if not account:
            return
        self._safety_dialog_presenter.clear()
        self.withdraw_notification("safety-review")

        if self.reconnect_window:
            old_reconnect = self.reconnect_window
            self.reconnect_window = None
            old_reconnect.close()

        def finalize() -> None:
            if self.settings_window:
                old_settings = self.settings_window
                self.settings_window = None
                old_settings.close()
            if self.tray:
                self.tray.stop()
                self.tray = None
            if self.runtime:
                self.runtime.stop()
                self.runtime = None
            if self.desktop_integration:
                self.desktop_integration.cleanup()
                self.desktop_integration.close()
                self.desktop_integration = None
            if self.main_window:
                old_window = self.main_window
                old_window.dispose_for_account_reset()
                self.remove_window(old_window)
                self.main_window = None
            self.config.reset_account()
            self.setup_window = SetupWindow(
                self, self.config, self.credentials, self._setup_complete
            )
            self.setup_window.present()

        def cleared(_ok: bool, _error: Exception | None) -> None:
            finalize()

        def secret_ready(password: str | None, _error: Exception | None) -> None:
            def clear_local(_revoked: bool = False) -> None:
                self.credentials.clear(
                    account["server_url"], account["login_name"], cleared
                )

            if password:
                NextcloudApi().revoke_app_password(
                    account["server_url"], account["login_name"], password, clear_local
                )
            else:
                clear_local()

        self.credentials.lookup(
            account["server_url"], account["login_name"], secret_ready
        )

    def _quit_when_ready(self) -> bool:
        if self.runtime and self.runtime.engine.running:
            return GLib.SOURCE_CONTINUE
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_shutdown(self) -> None:
        self._update_window_presenter.clear()
        self._safety_dialog_presenter.clear()
        self.update_checker.cancel()
        if self.bootstrap_window:
            self.bootstrap_window.runner.cancel()
        if self.settings_window:
            self.settings_window.close()
        if self.reconnect_window:
            self.reconnect_window.close()
        if self.tray:
            self.tray.stop()
        if self.runtime:
            self.runtime.stop()
        if self.desktop_integration:
            self.desktop_integration.close()
        self.logger.close()
        Adw.Application.do_shutdown(self)
