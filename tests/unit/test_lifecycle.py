from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


def method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == method_name:
                    return ast.get_source_segment(source, member) or ""
    raise AssertionError(f"{class_name}.{method_name} was not found")


class LifecycleContractTests(unittest.TestCase):
    def test_background_activation_keeps_the_main_window_lazy(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "application.py"
        activate = method_source(path, "PyNextCloudApplication", "do_activate")
        continue_activation = method_source(
            path, "PyNextCloudApplication", "_continue_activation"
        )
        self.assertIn("self._begin_startup_update_check()", activate)
        self.assertIn("self._ensure_tray()", continue_activation)
        self.assertNotIn("self._ensure_main_window()", activate)

    def test_update_check_precedes_runtime_and_mandatory_updates_block_it(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "application.py"
        activate = method_source(path, "PyNextCloudApplication", "do_activate")
        finished = method_source(
            path, "PyNextCloudApplication", "_startup_update_finished"
        )
        ensure_runtime = method_source(
            path, "PyNextCloudApplication", "_ensure_runtime"
        )
        self.assertIn("if not self._startup_update_complete", activate)
        self.assertIn("result.latest.mandatory", finished)
        self.assertIn("self._enter_mandatory_update_mode", finished)
        self.assertIn("self._continue_activation", finished)
        self.assertIn("self._mandatory_update_manifest", ensure_runtime)

    def test_about_exposes_the_manual_update_check(self) -> None:
        about = (ROOT / "src" / "pynextcloud_sync" / "ui" / "about.py").read_text(
            encoding="utf-8"
        )
        main_window = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn('about.add_link(_("Check for Updates")', about)
        self.assertIn('about.connect("activate-link"', about)
        self.assertIn("application.check_for_updates", main_window)

    def test_update_notice_is_a_full_window_with_native_expandable_changelog(self) -> None:
        source = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "update_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class UpdateWindow(Adw.ApplicationWindow)", source)
        self.assertIn("Adw.ExpanderRow(", source)
        self.assertIn("changelog.set_expanded(False)", source)
        self.assertNotIn("Adw.AlertDialog", source)

    def test_update_actions_are_fixed_before_the_scrollable_details(self) -> None:
        source = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "update_window.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            source.index('Gtk.Button(label=_("Download New Version"))'),
            source.index("scroller = Gtk.ScrolledWindow("),
        )
        self.assertIn("page.append(scroller)", source)
        self.assertNotIn('_("Open Releases Page")', source)

    def test_startup_update_waits_for_the_mapped_main_window(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "application.py"
        startup_finished = method_source(
            path, "PyNextCloudApplication", "_startup_update_finished"
        )
        queue_update = method_source(
            path,
            "PyNextCloudApplication",
            "_queue_update_window_for_mapped_parent",
        )
        present_main = method_source(path, "PyNextCloudApplication", "present_main")
        foreground = method_source(
            path,
            "PyNextCloudApplication",
            "_present_update_window_foreground",
        )
        self.assertIn("self._queue_update_window_for_mapped_parent", startup_finished)
        self.assertIn("self._update_window_presenter.queue(manifest, parent)", queue_update)
        self.assertIn("self._queue_update_window_for_mapped_parent", present_main)
        self.assertNotIn("set_transient_for", present_main)
        self.assertNotIn("set_transient_for", foreground)

    def test_mandatory_notice_uses_urgent_copy_and_replaces_not_now_with_quit(self) -> None:
        source = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "update_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"dialog-warning-symbolic"', source)
        self.assertIn('_("Mandatory update available")', source)
        self.assertIn('Gtk.Button(label=_("Close Application"))', source)
        self.assertNotIn("not_now.set_sensitive(False)", source)
        self.assertLess(
            source.index("if mandatory:\n            quit_button"),
            source.index("else:\n            not_now"),
        )

    def test_tray_settings_opens_an_independent_preferences_window(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        main_window = ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        settings = ROOT / "src" / "pynextcloud_sync" / "ui" / "settings.py"
        app_settings = method_source(
            application, "PyNextCloudApplication", "show_settings"
        )
        window_settings = method_source(main_window, "MainWindow", "show_settings")
        settings_source = settings.read_text(encoding="utf-8")
        self.assertIn("SettingsWindow(", app_settings)
        self.assertIn("self.settings_window.present()", app_settings)
        self.assertNotIn("self.present_main()", app_settings)
        self.assertNotIn("self._ensure_main_window()", app_settings)
        self.assertIn("application.show_settings()", window_settings)
        self.assertIn(
            "class SettingsWindow(Adw.PreferencesWindow)", settings_source
        )

    def test_desktop_integrations_are_initialized_only_after_new_setup(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        setup_complete = method_source(
            application, "PyNextCloudApplication", "_setup_complete"
        )
        bootstrap_complete = method_source(
            application, "PyNextCloudApplication", "_bootstrap_complete"
        )
        ensure_integration = method_source(
            application, "PyNextCloudApplication", "_ensure_desktop_integration"
        )
        self.assertIn("initialize_integrations=True", setup_complete)
        self.assertIn("initialize_defaults()", bootstrap_complete)
        self.assertNotIn("initialize_defaults()", ensure_integration)

    def test_existing_configuration_requires_bootstrap_before_runtime(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        activate = method_source(
            application, "PyNextCloudApplication", "_continue_activation"
        )
        ensure_runtime = method_source(
            application, "PyNextCloudApplication", "_ensure_runtime"
        )
        self.assertIn('"bootstrap_complete", False', activate)
        self.assertIn("self._ensure_bootstrap()", activate)
        self.assertIn('"bootstrap_complete", False', ensure_runtime)

    def test_missing_bootstrap_credential_can_return_to_account_setup(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        bootstrap = ROOT / "src" / "pynextcloud_sync" / "ui" / "bootstrap.py"
        ensure_bootstrap = method_source(
            application, "PyNextCloudApplication", "_ensure_bootstrap"
        )
        reconnect = method_source(
            application, "PyNextCloudApplication", "_bootstrap_reconnect_account"
        )
        bootstrap_source = bootstrap.read_text(encoding="utf-8")

        self.assertIn("self._bootstrap_reconnect_account", ensure_bootstrap)
        self.assertIn('label=_("Reconnect Account")', bootstrap_source)
        self.assertIn("credential_missing=not error", bootstrap_source)
        self.assertIn("old_bootstrap.completed = True", reconnect)
        self.assertIn("self.reconnect_account()", reconnect)
        self.assertNotIn("self.remove_account()", reconnect)

    def test_closed_main_window_releases_ui_subscriptions(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        close_handler = method_source(path, "MainWindow", "_hide_on_close")
        dispose = method_source(path, "MainWindow", "_dispose_ui")
        self.assertIn("self._dispose_ui()", close_handler)
        self.assertIn("self._state_unsubscribe()", dispose)
        self.assertIn("self._log_unsubscribe()", dispose)

    def test_log_and_sync_output_have_explicit_memory_limits(self) -> None:
        log_view = (ROOT / "src" / "pynextcloud_sync" / "ui" / "log_view.py").read_text(
            encoding="utf-8"
        )
        sync_engine = (
            ROOT / "src" / "pynextcloud_sync" / "core" / "sync_engine.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MAX_BUFFER_LINES = 2_000", log_view)
        self.assertIn("BoundedOutputCapture(max_lines=200)", sync_engine)

    def test_login_polling_allows_only_one_request_in_flight(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "nextcloud" / "login_flow.py"
        poll = method_source(path, "LoginFlowV2", "_poll")
        cancel = method_source(path, "LoginFlowV2", "cancel")
        self.assertIn("if self._poll_in_flight", poll)
        self.assertIn("self._poll_cancellable.cancel()", cancel)

    def test_manual_keyring_unlock_reconnects_push_and_sync_together(self) -> None:
        path = ROOT / "src" / "pynextcloud_sync" / "core" / "runtime.py"
        sync_now = method_source(path, "RuntimeController", "sync_now")
        self.assertIn("self.scheduler.keyring_locked", sync_now)
        self.assertIn("self.scheduler.request(Trigger.MANUAL)", sync_now)
        self.assertIn("self._configure_push(", sync_now)

    def test_account_attention_opens_the_account_preferences_page(self) -> None:
        main_window = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        ).read_text(encoding="utf-8")
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        settings = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "settings.py"
        ).read_text(encoding="utf-8")
        show_settings = method_source(
            application, "PyNextCloudApplication", "show_settings"
        )

        self.assertIn('snapshot.state == AppState.AUTH_REQUIRED', main_window)
        self.assertIn('application.show_settings("account")', main_window)
        self.assertIn("self.status_action.set_visible", main_window)
        self.assertIn("self._build_account()", settings)
        self.assertIn("self.settings_window.show_account_page()", show_settings)

    def test_safety_notification_is_urgent_and_opens_the_review_directly(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        install_actions = method_source(
            application, "PyNextCloudApplication", "_install_actions"
        )
        notify = method_source(
            application, "PyNextCloudApplication", "_notify_safety_alert"
        )
        open_review = method_source(
            application,
            "PyNextCloudApplication",
            "_review_safety_from_notification",
        )
        queued_review = method_source(
            application,
            "PyNextCloudApplication",
            "_show_queued_safety_review",
        )
        choose = method_source(
            application, "PyNextCloudApplication", "_safety_choice"
        )

        self.assertIn('("review-safety", self._review_safety_from_notification)', install_actions)
        self.assertIn("Gio.NotificationPriority.URGENT", notify)
        self.assertIn('notification.set_default_action("app.review-safety")', notify)
        self.assertIn('notification.add_button(_("Review Now"), "app.review-safety")', notify)
        self.assertIn("self._safety_dialog_presenter.queue", open_review)
        self.assertIn("self.review_safety_alert(parent)", queued_review)
        self.assertGreaterEqual(
            choose.count('self.withdraw_notification("safety-review")'),
            2,
        )

    def test_reconnect_preserves_the_existing_account_and_safety_baseline(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        reconnect = method_source(
            application, "PyNextCloudApplication", "reconnect_account"
        )
        completed = method_source(
            application, "PyNextCloudApplication", "_reconnect_complete"
        )

        self.assertIn("ReconnectWindow(", reconnect)
        self.assertIn("self.runtime.authentication_restored()", completed)
        self.assertNotIn("reset_account", reconnect + completed)
        self.assertNotIn('["bootstrap_complete"] =', reconnect + completed)
        self.assertNotIn("remove_account", reconnect + completed)

    def test_reconnect_uses_a_compact_header_without_internal_scrolling(self) -> None:
        source = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "reconnect.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Adw.StatusPage(", source)
        self.assertNotIn("Gtk.ScrolledWindow(", source)
        self.assertIn('pixel_size=64', source)
        self.assertIn('css_classes=["title-1"]', source)
        self.assertIn("description.set_max_width_chars(52)", source)

    def test_rate_limit_retries_the_same_new_authorization(self) -> None:
        reconnect = ROOT / "src" / "pynextcloud_sync" / "ui" / "reconnect.py"
        validation = method_source(
            reconnect, "ReconnectWindow", "_validate_result"
        )
        limited = method_source(
            reconnect, "ReconnectWindow", "_validation_limited"
        )

        self.assertIn("NextcloudRateLimitError", validation)
        self.assertIn("GLib.timeout_add_seconds", limited)
        self.assertIn("self._validate_result(result)", limited)
        self.assertNotIn("self.login_flow.start", limited)
        self.assertNotIn("self._reject_result", limited)

    def test_reconnect_reuses_validated_details_in_account_settings(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        completed = method_source(
            application, "PyNextCloudApplication", "_reconnect_complete"
        )
        updated = method_source(
            application, "PyNextCloudApplication", "_account_details_updated"
        )

        self.assertIn("account_details: AccountDetails", completed)
        self.assertIn("self._account_details_updated(account_details)", completed)
        self.assertIn("store_account_details(self.config, details)", updated)
        self.assertIn("self.settings_window.set_account_details(details)", updated)

    def test_home_shows_bounded_and_unlimited_storage_usage(self) -> None:
        main_window = ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        source = main_window.read_text(encoding="utf-8")
        details = method_source(main_window, "MainWindow", "set_storage_usage")

        self.assertIn("Gtk.ProgressBar(", source)
        self.assertIn("self.quota_progress.set_show_text(True)", source)
        self.assertIn("used / total", details)
        self.assertIn("self.quota_progress.set_fraction", details)
        self.assertIn('self.quota_progress.set_text(f"{percent}%")', details)
        self.assertIn('self.quota_progress.set_text("∞")', details)
        self.assertNotIn(".pulse()", source)
        self.assertNotIn("set_pulse_step", source)
        self.assertIn("Limited only by available server storage", details)

    def test_reconnect_reuses_validated_quota_on_the_home_page(self) -> None:
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        updated = method_source(
            application, "PyNextCloudApplication", "_account_details_updated"
        )

        self.assertIn("self.main_window.set_account_details(details)", updated)

    def test_remote_details_are_persistent_and_not_loaded_when_windows_open(self) -> None:
        main_window = ROOT / "src" / "pynextcloud_sync" / "ui" / "main_window.py"
        settings = ROOT / "src" / "pynextcloud_sync" / "ui" / "settings.py"
        main_source = main_window.read_text(encoding="utf-8")
        settings_source = settings.read_text(encoding="utf-8")
        show_account = method_source(settings, "SettingsWindow", "show_account_page")

        self.assertIn("cached_storage_usage(self.config)", main_source)
        self.assertNotIn("NextcloudApi", main_source)
        self.assertNotIn("credentials.lookup", main_source)
        self.assertIn("cached_account_details(self.config)", settings_source)
        self.assertIn("cached_server_details(self.config)", settings_source)
        self.assertNotIn("refresh_account_details", show_account)

    def test_startup_refreshes_remote_identity_and_server_once(self) -> None:
        runtime = ROOT / "src" / "pynextcloud_sync" / "core" / "runtime.py"
        refresher = (
            ROOT
            / "src"
            / "pynextcloud_sync"
            / "nextcloud"
            / "details_refresher.py"
        )
        start = method_source(runtime, "RuntimeController", "start")
        refresh_start = method_source(
            refresher, "RemoteDetailsRefresher", "start"
        )

        self.assertIn("self.details_refresher.start()", start)
        self.assertIn("self.refresh_account()", refresh_start)
        self.assertIn("self.refresh_server()", refresh_start)

    def test_successful_sync_refreshes_only_persistent_storage_usage(self) -> None:
        runtime = ROOT / "src" / "pynextcloud_sync" / "core" / "runtime.py"
        refresher = (
            ROOT
            / "src"
            / "pynextcloud_sync"
            / "nextcloud"
            / "details_refresher.py"
        )
        application = ROOT / "src" / "pynextcloud_sync" / "application.py"
        completed = method_source(runtime, "RuntimeController", "_sync_completed")
        refresh = method_source(
            refresher, "RemoteDetailsRefresher", "refresh_account"
        )
        storage = method_source(
            application, "PyNextCloudApplication", "_storage_usage_updated"
        )

        self.assertIn("result.successful", completed)
        self.assertIn(
            "self.details_refresher.refresh_account(storage_only=True)", completed
        )
        self.assertIn("if storage_only and self.storage_updated", refresh)
        self.assertIn("store_storage_usage(self.config, used, total)", storage)
        self.assertNotIn("store_account_details", storage)

    def test_browser_login_uses_a_stable_device_authorization_name(self) -> None:
        login_flow = (
            ROOT / "src" / "pynextcloud_sync" / "nextcloud" / "login_flow.py"
        ).read_text(encoding="utf-8")
        setup = (
            ROOT / "src" / "pynextcloud_sync" / "ui" / "setup.py"
        ).read_text(encoding="utf-8")

        self.assertIn("HttpClient(user_agent=authorization_name())", login_flow)
        self.assertIn('"authorization_name"', setup)


if __name__ == "__main__":
    unittest.main()
