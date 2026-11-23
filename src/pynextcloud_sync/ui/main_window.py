from __future__ import annotations

import datetime as dt
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from pynextcloud_sync import APP_NAME
from pynextcloud_sync.core.state import AppState, StateSnapshot
from pynextcloud_sync.nextcloud.activity import SyncPhase, SyncProgress
from pynextcloud_sync.nextcloud.api import AccountDetails
from pynextcloud_sync.storage.history import SyncSummary
from pynextcloud_sync.storage.remote_details import cached_storage_usage
from pynextcloud_sync.util.i18n import _, ngettext

from .about import show_about_dialog
from .activity import summary_row
from .history import HistoryWindow


STATE_PRESENTATION = {
    AppState.UNCONFIGURED: ("pynextcloud-sync-dialog-question-symbolic", _("Not Configured")),
    AppState.IDLE_OK: ("pynextcloud-sync-emblem-ok-symbolic", _("Synchronized")),
    AppState.IDLE_MANUAL_ONLY: ("pynextcloud-sync-media-playback-pause-symbolic", _("Automatic Sync Is Off")),
    AppState.SYNC_QUEUED: ("pynextcloud-sync-appointment-soon-symbolic", _("Synchronization Scheduled")),
    AppState.SYNCING: ("pynextcloud-sync-emblem-synchronizing-symbolic", _("Synchronizing…")),
    AppState.PAUSED_USER: ("pynextcloud-sync-media-playback-pause-symbolic", _("Paused")),
    AppState.PAUSED_BATTERY: ("pynextcloud-sync-battery-symbolic", _("Paused on Battery")),
    AppState.OFFLINE: ("pynextcloud-sync-network-offline-symbolic", _("Offline")),
    AppState.ERROR: ("pynextcloud-sync-dialog-error-symbolic", _("Synchronization Error")),
    AppState.AUTH_REQUIRED: ("pynextcloud-sync-dialog-password-symbolic", _("Account Needs Attention")),
    AppState.KEYRING_LOCKED: ("pynextcloud-sync-changes-prevent-symbolic", _("Password Keyring Locked")),
    AppState.SAFETY_REVIEW: ("pynextcloud-sync-security-high-symbolic", _("Safety Review Required")),
}

SYNC_PHASE_DESCRIPTIONS = {
    SyncPhase.CHECKING: _("Checking for changes…"),
    SyncPhase.APPLYING: _("Applying changes…"),
    SyncPhase.FINALIZING: _("Finalizing…"),
}


def _compact_action_row(**properties: object) -> Adw.ActionRow:
    row = Adw.ActionRow(**properties)
    if hasattr(row, "set_title_lines"):
        row.set_title_lines(1)
    if hasattr(row, "set_subtitle_lines"):
        row.set_subtitle_lines(1)
    return row


class _OperationMarks(Gtk.Box):
    """Display one segment per reported operation when the segments fit."""

    MIN_MARK_WIDTH = 5

    def __init__(self, description: str) -> None:
        super().__init__(homogeneous=True, spacing=3)
        self.set_tooltip_text(description)
        self.update_property([Gtk.AccessibleProperty.LABEL], [description])
        self._marks: list[Gtk.Box] = []
        self._counts = (0, 0)

    def fits(self, count: int, width: int) -> bool:
        return count * self.MIN_MARK_WIDTH + (count - 1) * self.get_spacing() <= width

    def show_counts(self, completed: int, active: int) -> None:
        if self._counts == (completed, active):
            return
        self._counts = (completed, active)
        total = completed + active
        while len(self._marks) < total:
            mark = Gtk.Box()
            self.append(mark)
            self._marks.append(mark)
        while len(self._marks) > total:
            self.remove(self._marks.pop())

        for index, mark in enumerate(self._marks):
            state = "confirmed" if index < completed else "running"
            mark.set_css_classes(["sync-operation-mark", state])


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Gtk.Application, config: object, runtime: object, logger: object) -> None:
        super().__init__(application=application, title=APP_NAME)
        self.set_default_size(720, 560)
        self.config = config
        self.runtime = runtime
        self.logger = logger
        self.history_window: HistoryWindow | None = None
        self._activity_rows: list[Gtk.ListBoxRow] = []
        self._safety_review_active = False
        self._disposed = False
        self._progress_source = 0

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=APP_NAME, subtitle=_("Nextcloud file synchronization")))
        settings = Gtk.Button(
            icon_name="pynextcloud-sync-emblem-system-symbolic", tooltip_text=_("Settings"), css_classes=["flat"]
        )
        settings.connect("clicked", self.show_settings)
        header.pack_end(settings)
        about = Gtk.Button(
            icon_name="pynextcloud-sync-help-about-symbolic", tooltip_text=_("About"), css_classes=["flat"]
        )
        about.connect("clicked", self._show_about)
        header.pack_end(about)
        toolbar.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay()
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=660, tightening_threshold=500)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(18)
        content.set_margin_end(18)
        clamp.set_child(content)
        scroller.set_child(clamp)
        self.toast_overlay.set_child(scroller)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

        status_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        status_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status_box.set_margin_top(14)
        status_box.set_margin_bottom(14)
        status_box.set_margin_start(16)
        status_box.set_margin_end(16)
        self.status_icon = Gtk.Image(icon_name="pynextcloud-sync-emblem-ok-symbolic", pixel_size=48)
        self.status_icon.set_valign(Gtk.Align.CENTER)
        status_box.append(self.status_icon)
        status_text = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            valign=Gtk.Align.CENTER,
            hexpand=True,
        )
        self.status_title = Gtk.Label(xalign=0, css_classes=["title-3"])
        self.status_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_title.set_single_line_mode(True)
        self.status_subtitle = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"])
        self.status_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_subtitle.set_single_line_mode(True)
        status_text.append(self.status_title)
        status_text.append(self.status_subtitle)
        self._progress_style = Gtk.CssProvider()
        self._progress_style.load_from_data(b"""
            progressbar.sync-status-progress > trough,
            progressbar.sync-status-progress > trough > progress { min-width: 0; min-height: 4px; }
            progressbar.sync-status-progress > trough { background-color: alpha(@accent_bg_color, 0.38); }
            .sync-operation-mark { min-height: 4px; border-radius: 2px; }
            .sync-operation-mark.running { background-color: alpha(@accent_bg_color, 0.38); }
            .sync-operation-mark.confirmed { background-color: @accent_bg_color; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), self._progress_style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        description = _("Reported operations")
        self._operation_summary = Gtk.ProgressBar(css_classes=["sync-status-progress"])
        self._operation_summary.set_tooltip_text(description)
        self._operation_summary.update_property([Gtk.AccessibleProperty.LABEL], [description])
        self._operation_marks = _OperationMarks(description)
        # Reserve the progress track's height so the other rows stay in place.
        self._progress_stack = Gtk.Stack(hhomogeneous=False)
        self._progress_stack.add_named(Gtk.Box(), "idle")
        self._progress_stack.add_named(self._operation_summary, "summary")
        self._progress_stack.add_named(self._operation_marks, "reported")
        status_text.append(self._progress_stack)
        status_box.append(status_text)
        self.status_action = Gtk.Button(
            label=_("View Account"),
            css_classes=["suggested-action", "pill"],
            valign=Gtk.Align.CENTER,
            visible=False,
        )
        self.status_action.connect("clicked", self._show_account_settings)
        status_box.append(self.status_action)
        status_row.set_child(status_box)
        status_list.append(status_row)
        content.append(status_list)

        account = self.config.data["account"]
        account_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        account_list.append(
            _compact_action_row(
                title=account["login_name"],
                subtitle=account["server_url"],
                icon_name="pynextcloud-sync-avatar-default-symbolic",
            )
        )
        folder_row = _compact_action_row(
            title=_("Local Folder"),
            subtitle=account["local_root"],
            icon_name="pynextcloud-sync-folder-symbolic",
            activatable=True,
        )
        folder_row.add_suffix(Gtk.Image.new_from_icon_name("pynextcloud-sync-go-next-symbolic"))
        folder_row.connect("activated", lambda _row: self.open_folder())
        account_list.append(folder_row)
        quota_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        quota_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        quota_box.set_margin_top(10)
        quota_box.set_margin_bottom(10)
        quota_box.set_margin_start(14)
        quota_box.set_margin_end(14)
        quota_icon = Gtk.Image(
            icon_name="pynextcloud-sync-drive-harddisk-symbolic",
            pixel_size=20,
            valign=Gtk.Align.CENTER,
        )
        quota_box.append(quota_icon)
        quota_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=5,
            hexpand=True,
        )
        quota_title = Gtk.Label(
            label=_("Storage usage"),
            xalign=0,
        )
        quota_content.append(quota_title)
        self.quota_description = Gtk.Label(
            label=_("Available after the first successful synchronization"),
            xalign=0,
            wrap=True,
            css_classes=["dim-label"],
        )
        quota_content.append(self.quota_description)
        self.quota_progress = Gtk.ProgressBar(hexpand=True)
        self.quota_progress.set_show_text(True)
        self.quota_progress.set_text("")
        self.quota_progress.set_tooltip_text(_("Account storage usage"))
        quota_content.append(self.quota_progress)
        quota_box.append(quota_content)
        quota_row.set_child(quota_box)
        account_list.append(quota_row)
        content.append(account_list)

        self.buttons = Gtk.Box(spacing=12, homogeneous=True)
        self.sync_content = Adw.ButtonContent(
            label=_("Sync Now"), icon_name="pynextcloud-sync-emblem-synchronizing-symbolic"
        )
        self.sync_button = Gtk.Button(child=self.sync_content, css_classes=["suggested-action", "pill"])
        self.sync_button.connect("clicked", self._sync_clicked)
        self.buttons.append(self.sync_button)
        self.pause_content = Adw.ButtonContent(
            label=_("Pause Sync"), icon_name="pynextcloud-sync-media-playback-pause-symbolic"
        )
        self.pause_button = Gtk.Button(child=self.pause_content, css_classes=["pill"])
        self.pause_button.connect("clicked", self._pause_clicked)
        self.buttons.append(self.pause_button)
        content.append(self.buttons)

        activity_heading = Gtk.Label(
            label=_("Recent Activity"), xalign=0, css_classes=["heading"],
        )
        activity_heading.set_margin_start(4)
        content.append(activity_heading)
        self.activity_list = Gtk.ListBox(
            css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
        )
        self.view_history_row = _compact_action_row(
            title=_("View Synchronization History"),
            icon_name="pynextcloud-sync-document-open-recent-symbolic",
            activatable=True,
        )
        self.view_history_row.add_suffix(Gtk.Image.new_from_icon_name("pynextcloud-sync-go-next-symbolic"))
        self.view_history_row.connect("activated", lambda _row: self._show_history())
        self.activity_list.append(self.view_history_row)
        content.append(self.activity_list)

        if hasattr(Adw, "Breakpoint") and hasattr(self, "add_breakpoint"):
            condition = Adw.BreakpointCondition.parse("max-width: 520px")
            breakpoint = Adw.Breakpoint.new(condition)
            breakpoint.add_setter(self.buttons, "orientation", Gtk.Orientation.VERTICAL)
            breakpoint.add_setter(content, "margin-start", 9)
            breakpoint.add_setter(content, "margin-end", 9)
            self.add_breakpoint(breakpoint)

        self._state_unsubscribe = self.runtime.state.subscribe(self._state_changed)
        self._history_unsubscribe = self.runtime.history.subscribe(self._refresh_activity)
        self._refresh_activity()
        self.connect("close-request", self._hide_on_close)
        self.connect("map", self._track_sync_progress)
        self.connect("unmap", self._stop_progress_updates)
        storage = cached_storage_usage(self.config)
        if storage:
            self.set_storage_usage(storage.used, storage.total)

    def set_account_details(self, details: AccountDetails) -> None:
        self.set_storage_usage(details.quota_used, details.quota_total)

    def set_storage_usage(self, used: int | None, total: int | None) -> None:
        if self._disposed:
            return
        if used is None:
            self.quota_progress.set_fraction(0.0)
            self.quota_progress.set_text("")
            self.quota_description.set_text(_("Storage usage was not reported"))
            return
        used_text = GLib.format_size(max(0, used))
        if total is not None and total > 0:
            fraction = min(max(used / total, 0.0), 1.0)
            percent = round(fraction * 100)
            self.quota_progress.set_fraction(fraction)
            self.quota_progress.set_text(f"{percent}%")
            self.quota_description.set_text(
                _("{used} of {total} used · {percent}%").format(
                    used=used_text,
                    total=GLib.format_size(total),
                    percent=percent,
                )
            )
            return
        self.quota_description.set_text(
            _("{used} used · Limited only by available server storage").format(
                used=used_text
            )
        )
        self.quota_progress.set_fraction(0.0)
        self.quota_progress.set_text("∞")

    def _state_changed(self, snapshot: StateSnapshot) -> None:
        icon, title = STATE_PRESENTATION[snapshot.state]
        self.status_icon.set_from_icon_name(icon)
        self.status_title.set_text(title)
        self._track_sync_progress()
        if snapshot.state == AppState.IDLE_OK:
            self.status_icon.add_css_class("success")
        else:
            self.status_icon.remove_css_class("success")
        paused = snapshot.state == AppState.PAUSED_USER
        self.pause_content.set_label(_("Resume Sync") if paused else _("Pause Sync"))
        self.pause_content.set_icon_name(
            "pynextcloud-sync-media-playback-start-symbolic" if paused else "pynextcloud-sync-media-playback-pause-symbolic"
        )
        self.status_action.set_visible(snapshot.state == AppState.AUTH_REQUIRED)
        if snapshot.state == AppState.SAFETY_REVIEW:
            self.sync_content.set_label(_("Review Safety Alert"))
            self.sync_content.set_icon_name("pynextcloud-sync-security-high-symbolic")
        elif snapshot.state == AppState.KEYRING_LOCKED:
            self.sync_content.set_label(_("Unlock Password Keyring"))
            self.sync_content.set_icon_name("pynextcloud-sync-changes-prevent-symbolic")
        elif snapshot.state == AppState.AUTH_REQUIRED:
            self.sync_content.set_label(_("Reconnect Account"))
            self.sync_content.set_icon_name("pynextcloud-sync-view-refresh-symbolic")
        else:
            self.sync_content.set_label(
                _("Sync Once")
                if snapshot.state in {AppState.PAUSED_USER, AppState.PAUSED_BATTERY}
                else _("Sync Now")
            )
            self.sync_content.set_icon_name("pynextcloud-sync-emblem-synchronizing-symbolic")
        needs_review = snapshot.state == AppState.SAFETY_REVIEW
        if self._safety_review_active != needs_review and self.history_window:
            self.history_window.activity.refresh()
        self._safety_review_active = needs_review

    def _track_sync_progress(self, _window: Gtk.Widget | None = None) -> None:
        self._stop_progress_updates()
        if self._update_sync_progress() and self.get_mapped():
            self._progress_source = GLib.timeout_add(160, self._update_sync_progress)

    def _stop_progress_updates(self, _window: Gtk.Widget | None = None) -> None:
        if self._progress_source:
            GLib.source_remove(self._progress_source)
            self._progress_source = 0

    def _update_sync_progress(self) -> bool:
        snapshot = self.runtime.state.snapshot
        progress = self.runtime.engine.progress
        if progress is None and snapshot.state == AppState.SYNCING:
            progress = SyncProgress()
        if progress is None:
            self._progress_source = 0
            self._progress_stack.set_visible_child_name("idle")
            description = _(snapshot.message) if snapshot.message else ""
            subtitle = self._format_last_sync()
            if description and description.casefold() != self.status_title.get_text().casefold():
                subtitle = f"{subtitle} · {description}"
            self._set_status_subtitle(subtitle)
            return GLib.SOURCE_REMOVE

        progress_view = "idle"
        subtitle = SYNC_PHASE_DESCRIPTIONS[progress.phase]
        if progress.phase == SyncPhase.CHECKING and not self.config.data["sync"].get("detailed_output", True):
            subtitle = self._format_last_sync()
        elif progress.phase == SyncPhase.APPLYING:
            total = progress.completed + progress.active
            if total:
                if self._operation_marks.fits(total, self._progress_stack.get_width()):
                    progress_view = "reported"
                    self._operation_marks.show_counts(progress.completed, progress.active)
                else:
                    progress_view = "summary"
                    self._operation_summary.set_fraction(progress.completed / total)
            if progress.completed:
                subtitle = ngettext(
                    "{count} operation completed", "{count} operations completed", progress.completed,
                ).format(count=progress.completed)
                if progress.active:
                    subtitle = _("{completed} · {active} in progress").format(
                        completed=subtitle, active=progress.active,
                    )
            elif progress.active:
                subtitle = ngettext(
                    "{count} operation in progress", "{count} operations in progress", progress.active,
                ).format(count=progress.active)
        self._progress_stack.set_visible_child_name(progress_view)
        self._set_status_subtitle(subtitle)
        return GLib.SOURCE_CONTINUE

    def _set_status_subtitle(self, subtitle: str) -> None:
        if self.status_subtitle.get_text() != subtitle:
            self.status_subtitle.set_text(subtitle)
            self.status_subtitle.set_tooltip_text(subtitle)

    def _format_last_sync(self) -> str:
        value = self.config.data["runtime"].get("last_successful_sync")
        if not value:
            return _("Not yet synchronized")
        try:
            stamp = dt.datetime.fromisoformat(value).astimezone()
        except (ValueError, TypeError):
            return str(value)
        time_text = stamp.strftime("%H:%M" if stamp.date() == dt.date.today() else "%x %H:%M")
        return _("Last successful sync · {time}").format(time=time_text)

    def _refresh_activity(self) -> None:
        self.runtime.history.recent(3, self._show_recent_activity)

    def _show_recent_activity(self, entries: list[SyncSummary]) -> None:
        if self._disposed:
            return
        for row in self._activity_rows:
            self.activity_list.remove(row)
        if entries:
            self._activity_rows = []
            for entry in entries:
                row = Adw.ActionRow(activatable=False)
                summary_row(entry, row)
                self._activity_rows.append(row)
        else:
            self._activity_rows = [
                Adw.ActionRow(title=_("No synchronization activity yet"), activatable=False)
            ]
        for index, row in enumerate(self._activity_rows):
            self.activity_list.insert(row, index)

    def _sync_clicked(self, _button: Gtk.Button) -> None:
        if self.runtime.state.snapshot.state == AppState.AUTH_REQUIRED:
            self._show_account_settings()
            return
        if self.runtime.scheduler.safety_alert:
            application = self.get_application()
            if application:
                application.review_safety_alert(self)
            return
        if self.runtime.scheduler.battery_paused:
            dialog = Adw.AlertDialog(
                heading=_("Synchronization is paused on battery"),
                body=_("Run one synchronization without changing the power preference?"),
            )
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("sync", _("Sync Once"))
            dialog.set_response_appearance("sync", Adw.ResponseAppearance.SUGGESTED)
            dialog.choose(self, None, self._battery_choice)
            return
        self.runtime.sync_now()

    def _show_account_settings(self, _button: Gtk.Button | None = None) -> None:
        application = self.get_application()
        if application:
            application.show_settings("account")

    def _battery_choice(self, dialog: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
        if dialog.choose_finish(result) == "sync":
            self.runtime.sync_now()

    def _pause_clicked(self, _button: Gtk.Button) -> None:
        self.runtime.set_paused(not self.runtime.scheduler.user_paused)

    def open_folder(self) -> None:
        root = Path(self.config.data["account"]["local_root"])
        root.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(root.as_uri(), None)

    def show_log(self) -> None:
        self._show_history(technical=True)

    def _show_history(self, *, technical: bool = False) -> None:
        if self._disposed:
            return
        if not self.history_window:
            self.history_window = HistoryWindow(
                self, self.runtime.history, self.logger, self.runtime.scheduler,
            )
            self.history_window.connect("close-request", self._history_closed)
        self.history_window.select_page(technical=technical)
        self.history_window.present()

    def show_settings(self, _button: Gtk.Button | None = None) -> None:
        if self._disposed:
            return
        application = self.get_application()
        if application:
            application.show_settings()

    def _history_closed(self, _window: Gtk.Window) -> bool:
        self.history_window = None
        if not self.get_visible() and not self._disposed:
            GLib.idle_add(self.close)
        return False

    def _show_about(self, _button: Gtk.Button) -> None:
        application = self.get_application()
        check_for_updates = (
            application.check_for_updates
            if application and hasattr(application, "check_for_updates")
            else None
        )
        show_about_dialog(self, check_for_updates)

    def _hide_on_close(self, _window: Gtk.Window) -> bool:
        self._dispose_ui()
        application = self.get_application()
        if application:
            application.main_window_closed(self)
        return False

    def _dispose_ui(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._stop_progress_updates()
        Gtk.StyleContext.remove_provider_for_display(self.get_display(), self._progress_style)
        self._state_unsubscribe()
        self._history_unsubscribe()
        if self.history_window:
            self.history_window.close()
            self.history_window = None

    def dispose_for_account_reset(self) -> None:
        self._dispose_ui()
        self.set_visible(False)
