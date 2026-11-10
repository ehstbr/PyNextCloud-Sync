from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from pynextcloud_sync.core.bootstrap import (
    BootstrapAnalysis,
    BootstrapPaused,
    BootstrapPolicy,
    BootstrapResult,
    BootstrapRunner,
)
from pynextcloud_sync.core.bootstrap_checkpoint import CheckpointError
from pynextcloud_sync.core.bootstrap_progress import BootstrapProgress
from pynextcloud_sync.nextcloud.api import NextcloudApi
from pynextcloud_sync.nextcloud.http import HttpClient
from pynextcloud_sync.storage.remote_details import cached_storage_usage
from pynextcloud_sync.util.i18n import _, ngettext


POLICY_OPTIONS = (
    (
        BootstrapPolicy.MERGE_NEWEST,
        _("Merge safely — keep both versions"),
        _("Recommended. The newest version keeps the original name and the other is preserved as a dated copy."),
    ),
    (
        BootstrapPolicy.NEXTCLOUD_FIRST,
        _("Give priority to Nextcloud"),
        _("The Nextcloud version keeps the original name; the computer version is preserved as a dated copy."),
    ),
    (
        BootstrapPolicy.COMPUTER_FIRST,
        _("Give priority to this computer"),
        _("The computer version keeps the original name; the Nextcloud version is preserved as a dated copy."),
    ),
    (
        BootstrapPolicy.REVIEW,
        _("Review every conflict"),
        _("Choose the preferred original version separately for every conflicting path."),
    ),
)


class BootstrapWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        application: Gtk.Application,
        config: object,
        credentials: object,
        logger: object,
        on_complete: Callable[[], None],
        on_reconnect_account: Callable[[], None],
        *,
        recovery: bool = False,
    ) -> None:
        title = _("Safety Review") if recovery else _("Safe Initial Synchronization")
        super().__init__(application=application, title=title)
        self.set_default_size(700, 700)
        self.config = config
        self.credentials = credentials
        self.logger = logger
        self.on_complete = on_complete
        self.on_reconnect_account = on_reconnect_account
        self.recovery = recovery
        self._mailbox_lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=120)
        self._log_dirty = False
        self._pending_progress: BootstrapProgress | None = None
        self._progress: BootstrapProgress | None = None
        self._last_activity = 0.0
        self._update_source = 0
        self._working = self._worker_started = self._applying = False
        self._pause_requested = self._exit_after_work = False
        self._properties_request: Gio.Cancellable | None = None
        storage = cached_storage_usage(config)
        self._quota_used = max(0, storage.used or 0) if storage else 0
        self.runner = BootstrapRunner(config, logger, self._record_log)
        self.analysis: BootstrapAnalysis | None = None
        self.password = ""
        self.completed = False
        self.conflict_rows: dict[str, Adw.ComboRow] = {}

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.details_button = Gtk.ToggleButton(label=_("View Details"))
        self.details_button.connect("toggled", self._toggle_details)
        header.pack_end(self.details_button)
        toolbar.add_top_bar(header)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack = Gtk.Stack(
            vexpand=True,
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=200,
        )
        content.append(self.stack)
        self._build_details(content)
        toolbar.set_content(content)
        self.set_content(toolbar)
        self._build_progress_page()
        self._build_review_page()
        self._build_error_page()
        self.stack.set_visible_child_name("progress")
        self.connect("close-request", self._on_close_request)
        if self.runner.has_pending_operation:
            self._show_paused(reopening=True)
        else:
            GLib.idle_add(self._begin_analysis)

    def _build_details(self, content: Gtk.Box) -> None:
        self.details_revealer = Gtk.Revealer()
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        details.set_margin_start(12)
        details.set_margin_end(12)
        details.set_margin_bottom(12)

        actions = Gtk.Box(spacing=8)
        self.auto_scroll = Gtk.CheckButton(label=_("Auto-scroll"), active=True)
        actions.append(self.auto_scroll)
        copy = Gtk.Button(label=_("Copy Details"))
        copy.connect("clicked", self._copy_details)
        actions.append(copy)
        details.append(actions)

        self.log_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        scroller = Gtk.ScrolledWindow(min_content_height=152)
        scroller.set_child(self.log_view)
        details.append(scroller)
        self.details_revealer.set_child(details)
        content.append(self.details_revealer)

    def _toggle_details(self, button: Gtk.ToggleButton) -> None:
        self.details_revealer.set_reveal_child(button.get_active())
        if button.get_active():
            self._render_details()

    def show_details(self) -> None:
        self.details_button.set_active(True)

    def _record_log(self, line: str) -> None:
        line = self.logger.redactor.redact(line)
        with self._mailbox_lock:
            self._lines.append(line[:768])
            self._log_dirty = True

    def _render_details(self) -> None:
        with self._mailbox_lock:
            self._log_dirty = False
            text = "\n".join(self._lines)
        buffer = self.log_view.get_buffer()
        buffer.set_text(text)
        if self.auto_scroll.get_active():
            buffer.place_cursor(buffer.get_end_iter())
            self.log_view.scroll_mark_onscreen(buffer.get_insert())

    def _copy_details(self, _button: Gtk.Button) -> None:
        with self._mailbox_lock:
            text = "\n".join(self._lines)
        self.get_clipboard().set(text)

    def _build_progress_page(self) -> None:
        page = Adw.Clamp(maximum_size=540, tightening_threshold=410)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        page.set_child(box)

        icon = Gtk.Image.new_from_icon_name("security-high-symbolic")
        icon.set_pixel_size(48)
        box.append(icon)
        self.progress_label = Gtk.Label(
            wrap=True, justify=Gtk.Justification.CENTER, css_classes=["title-2"]
        )
        box.append(self.progress_label)
        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER)
        box.append(self.spinner)
        self.bar = Gtk.ProgressBar(visible=False)
        box.append(self.bar)
        self.metrics_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        box.append(self.metrics_label)
        self.file_label = Gtk.Label(
            ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=56, css_classes=["dim-label"]
        )
        box.append(self.file_label)
        self.activity_label = Gtk.Label(
            wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"]
        )
        box.append(self.activity_label)

        actions = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.pause_button = Gtk.Button(label=_("Pause"), visible=False)
        self.pause_button.connect("clicked", self._request_pause)
        actions.append(self.pause_button)
        self.continue_button = Gtk.Button(
            label=_("Continue"), visible=False, css_classes=["suggested-action"]
        )
        self.continue_button.connect("clicked", lambda _button: self._begin_analysis())
        actions.append(self.continue_button)
        box.append(actions)
        self.stack.add_named(page, "progress")

    def _show_paused(self, *, reopening: bool = False) -> None:
        self.stack.set_visible_child_name("progress")
        self.progress_label.set_text(
            _("Protected synchronization is waiting to continue")
            if reopening else _("Protected synchronization paused")
        )
        self.metrics_label.set_text(_(
            "Continue to check the saved operation. A completed protected copy can be reused."
        ))
        self.bar.set_visible(False)
        self.spinner.set_visible(False)
        self.spinner.set_spinning(False)
        self.file_label.set_text("")
        self.activity_label.set_text("")
        self.pause_button.set_visible(False)
        self.continue_button.set_visible(True)

    def _request_pause(self, _button: Gtk.Button | None = None) -> None:
        self._pause_requested = True
        self.runner.pause()
        if self._progress:
            self._set_progress(self._progress)

    def _queue_progress(self, progress: BootstrapProgress) -> None:
        with self._mailbox_lock:
            self._pending_progress = progress

    def _start_updates(self) -> None:
        self._last_activity = time.monotonic()
        if not self._update_source:
            self._update_source = GLib.timeout_add(250, self._refresh_progress)

    def _stop_updates(self) -> None:
        with self._mailbox_lock:
            self._pending_progress = None
        if self._update_source:
            GLib.source_remove(self._update_source)
            self._update_source = 0
        if self.details_button.get_active():
            self._render_details()

    def _refresh_progress(self) -> bool:
        with self._mailbox_lock:
            progress = self._pending_progress
            self._pending_progress = None
            log_dirty = self._log_dirty
        if progress and progress != self._progress:
            self._last_activity = time.monotonic()
            self._set_progress(progress)
        if log_dirty:
            if self.details_button.get_active():
                self._render_details()
            else:
                with self._mailbox_lock:
                    self._log_dirty = False
            self._last_activity = time.monotonic()
        seconds = int(time.monotonic() - self._last_activity)
        if self._exit_after_work:
            activity = _("The app will close at the next safe stopping point.")
        elif seconds >= 5:
            activity = _("Last activity {seconds} s ago").format(seconds=seconds)
        else:
            activity = ""
        if activity != self.activity_label.get_text():
            self.activity_label.set_text(activity)
        return GLib.SOURCE_CONTINUE

    def _set_progress(self, progress: BootstrapProgress) -> None:
        self._progress = progress
        self.progress_label.set_text(progress.message)
        fraction = None
        metrics = ""
        if progress.downloading:
            size = GLib.format_size(progress.bytes_done)
            observed = progress.bytes_done + progress.partial_bytes
            if self._quota_used and observed < self._quota_used:
                fraction = observed / self._quota_used
                metrics = _("{used} of about {total} · {percent}% estimated").format(
                    used=GLib.format_size(observed),
                    total=GLib.format_size(self._quota_used),
                    percent=int(100 * fraction),
                )
            else:
                metrics = _("{size} downloaded").format(size=size)
            metrics += "\n" + ngettext(
                "{count} file completed", "{count} files completed", progress.items
            ).format(count=progress.items)
            if progress.partial_bytes:
                metrics += "\n" + _("{size} in progress").format(
                    size=GLib.format_size(progress.partial_bytes)
                )
            if progress.free_bytes is not None:
                metrics += "\n" + _("{size} free on the staging drive").format(
                    size=GLib.format_size(progress.free_bytes)
                )
        elif progress.total_items is not None:
            total = progress.total_items
            fraction = progress.items / total if total else 1.0
            metrics = _("{done} of {total} items processed").format(
                done=progress.items, total=total
            )
        elif progress.counted:
            metrics = ngettext(
                "{count} item found", "{count} items found", progress.items
            ).format(count=progress.items)

        self.metrics_label.set_text(metrics)
        self.bar.set_visible(fraction is not None)
        self.spinner.set_visible(fraction is None)
        self.spinner.set_spinning(fraction is None)
        if fraction is not None:
            self.bar.set_fraction(min(1.0, max(0.0, fraction)))
        filename = progress.current
        if filename and progress.file_size:
            filename = _("{file} · {read} of {total} read").format(
                file=filename,
                read=GLib.format_size(progress.file_bytes),
                total=GLib.format_size(progress.file_size),
            )
        self.file_label.set_text(filename)
        self.file_label.set_tooltip_text(progress.current or None)

        self.pause_button.set_visible(self._worker_started and not self._applying)
        self.pause_button.set_sensitive(not self._pause_requested)
        if self._pause_requested:
            self.pause_button.set_label(_("Pause Requested"))
        else:
            self.pause_button.set_label(
                _("Pause After Download") if progress.downloading else _("Pause")
            )

    def _build_review_page(self) -> None:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=460)
        self.review_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.review_content.set_margin_top(24)
        self.review_content.set_margin_bottom(24)
        self.review_content.set_margin_start(18)
        self.review_content.set_margin_end(18)
        clamp.set_child(self.review_content)
        scroller.set_child(clamp)
        self.stack.add_named(scroller, "review")

    def _build_error_page(self) -> None:
        page = Adw.StatusPage(
            icon_name="dialog-error-symbolic",
            title=_("Safety analysis could not finish"),
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        page.set_child(box)
        self.error_label = Gtk.Label(wrap=True, selectable=True, justify=Gtk.Justification.CENTER)
        box.append(self.error_label)
        self.retry_button = Gtk.Button(
            label=_("Try Again"),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        self.retry_button.connect("clicked", lambda _button: self._begin_analysis(restart=self._retry_fresh))
        box.append(self.retry_button)
        self.reconnect_button = Gtk.Button(
            label=_("Reconnect Account"),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        self.reconnect_button.connect(
            "clicked", lambda _button: self.on_reconnect_account()
        )
        self.reconnect_button.set_visible(False)
        box.append(self.reconnect_button)
        self.stack.add_named(page, "error")

    def _begin_analysis(self, *, restart: bool = False) -> bool:
        if self.completed or self._working:
            return GLib.SOURCE_REMOVE
        self.analysis = None
        self._applying = False
        self._pause_requested = False
        self.continue_button.set_visible(False)
        self.pause_button.set_visible(False)
        self.stack.set_visible_child_name("progress")
        with self._mailbox_lock:
            self._pending_progress = None
            self._lines.clear()
            self._log_dirty = True
        self._set_progress(BootstrapProgress(_("Unlocking the account credential…")))
        self._start_updates()
        account = self.config.data["account"]
        self._working = True

        def secret_ready(password: str | None, error: Exception | None) -> None:
            if self.completed or self._exit_after_work:
                return
            if error or not password:
                self._show_error(
                    str(error or _("No stored credential was found for this account.")),
                    credential_missing=not error,
                )
                return
            self.password = password
            self.logger.add_secret(password)
            def begin(remote_etag: str | None, _used: int | None) -> None:
                if self.completed:
                    return
                try:
                    self.runner.analyze(
                        password, self._queue_progress,
                        lambda analysis, failure: GLib.idle_add(
                            self._analysis_ready, analysis, failure
                        ),
                        restart=restart, remote_etag=remote_etag,
                    )
                    self._worker_started = True
                except Exception as exc:
                    self._show_error(str(exc))

            self._set_progress(BootstrapProgress(_("Checking the Nextcloud folder…")))
            self._request_properties(begin)

        self.credentials.lookup(account["server_url"], account["login_name"], secret_ready)
        return GLib.SOURCE_REMOVE

    def _request_properties(
        self, callback: Callable[[str | None, int | None], None]
    ) -> None:
        def loaded(etag: str | None, used: int | None) -> None:
            self._properties_request = None
            if not self.completed:
                if used is not None and used > 0:
                    self._quota_used = used
                callback(etag, used)

        try:
            http = HttpClient(timeout=5)
            network = self.config.data["network"]
            http.trust_invalid_certificates = bool(network.get("trust_invalid_certificates"))
            if proxy := network.get("custom_proxy"):
                http.session.set_proxy_resolver(Gio.SimpleProxyResolver.new(proxy, None))
            account = self.config.data["account"]
            self._properties_request = NextcloudApi(http).get_protected_root_properties(
                account["server_url"], account["login_name"], self.password, loaded
            )
        except Exception as exc:
            self.logger.warning("Could not request protected folder properties: %s", exc)
            loaded(None, None)

    def _analysis_ready(
        self,
        analysis: BootstrapAnalysis | None,
        error: Exception | None,
    ) -> bool:
        if self.completed:
            return GLib.SOURCE_REMOVE
        self._working = self._worker_started = False
        self._stop_updates()
        if self._exit_after_work:
            self.get_application().quit()
        elif isinstance(error, BootstrapPaused) or (analysis and self._pause_requested):
            self._show_paused()
        elif error or not analysis:
            self._show_error(
                str(error or _("The safety analysis returned no result.")),
                restart=isinstance(error, CheckpointError),
            )
        else:
            self.analysis = analysis
            self._populate_review(analysis)
            self.stack.set_visible_child_name("review")
        return GLib.SOURCE_REMOVE

    def _populate_review(self, analysis: BootstrapAnalysis) -> None:
        while child := self.review_content.get_first_child():
            self.review_content.remove(child)
        self.conflict_rows.clear()

        heading = Gtk.Label(
            label=_("Review before synchronizing"),
            xalign=0,
            css_classes=["title-1"],
        )
        self.review_content.append(heading)
        explanation = Gtk.Label(
            label=_(
                "Nothing has been deleted. Choose how the initial merge should be applied. Every conflicting version is preserved under a clear dated name."
            ),
            wrap=True,
            xalign=0,
            css_classes=["dim-label"],
        )
        self.review_content.append(explanation)

        if analysis.resumed:
            self.review_content.append(Adw.Banner(
                title=_("This review uses a saved protected copy. The app checks Nextcloud again before applying the merge."),
                revealed=True,
            ))
            refresh = Gtk.Button(label=_("Download a New Copy"), halign=Gtk.Align.START)
            refresh.connect("clicked", lambda _button: self._begin_analysis(restart=True))
            self.review_content.append(refresh)

        summary = Adw.PreferencesGroup(title=_("Analysis Summary"))
        for title, value, icon in (
            (_("Files on this computer"), analysis.local_file_count, "computer-symbolic"),
            (_("Files on Nextcloud"), analysis.remote_file_count, "network-server-symbolic"),
            (_("Only on this computer"), len(analysis.local_only), "go-up-symbolic"),
            (_("Only on Nextcloud"), len(analysis.remote_only), "go-down-symbolic"),
            (_("Identical paths"), len(analysis.identical), "emblem-ok-symbolic"),
            (_("Conflicts requiring a policy"), len(analysis.conflicts), "dialog-warning-symbolic"),
        ):
            summary.add(Adw.ActionRow(title=title, subtitle=str(value), icon_name=icon))
        self.review_content.append(summary)

        if analysis.legacy_databases:
            warning = Adw.Banner(
                title=_(
                    "An old synchronization database was found. It will be archived outside the synchronized folder and will never be reused silently."
                ),
                revealed=True,
            )
            self.review_content.append(warning)

        if analysis.unsupported or analysis.local.errors or analysis.remote.errors:
            details = list(analysis.unsupported) + analysis.local.errors + analysis.remote.errors
            banner = Adw.Banner(
                title=_(
                    "The analysis found unreadable, symbolic-link, or special paths. Choose another folder or correct them before continuing."
                ),
                revealed=True,
            )
            self.review_content.append(banner)
            self.review_content.append(
                Gtk.Label(label="\n".join(details[:20]), wrap=True, xalign=0, selectable=True)
            )

        if analysis.required_download_bytes > analysis.free_bytes:
            self.review_content.append(
                Adw.Banner(
                    title=_("There is not enough free space to copy the reviewed Nextcloud files into the local folder."),
                    revealed=True,
                )
            )

        if analysis.conflicts:
            policy_group = Adw.PreferencesGroup(title=_("Conflict Policy"))
            self.policy_row = Adw.ComboRow(
                title=_("Default decision"),
                subtitle=POLICY_OPTIONS[0][2],
                model=Gtk.StringList.new([option[1] for option in POLICY_OPTIONS]),
                selected=0,
            )
            self.policy_row.connect("notify::selected", self._policy_changed)
            policy_group.add(self.policy_row)
            self.review_content.append(policy_group)

            self.conflict_group = Adw.PreferencesGroup(
                title=_("Individual Conflict Decisions"),
                visible=False,
            )
            choices = Gtk.StringList.new(
                [
                    _("Keep both — newest at original path"),
                    _("Nextcloud version at original path"),
                    _("Computer version at original path"),
                ]
            )
            for conflict in analysis.conflicts:
                subtitle = (
                    _("File and folder use the same path")
                    if conflict.kind == "type"
                    else _("Different file contents")
                )
                row = Adw.ComboRow(
                    title=conflict.path,
                    subtitle=subtitle,
                    model=choices,
                    selected=0,
                )
                self.conflict_rows[conflict.path] = row
                self.conflict_group.add(row)
            self.review_content.append(self.conflict_group)
        else:
            self.policy_row = None

        path_group = Adw.PreferencesGroup(title=_("Path Preview"))
        preview = self._path_preview(analysis)
        path_group.add(
            Adw.ActionRow(
                title=_("Planned additions and conflicts"),
                subtitle=preview or _("No file transfer is required."),
                icon_name="view-list-symbolic",
            )
        )
        self.review_content.append(path_group)

        assurance = Gtk.Label(
            label=_(
                "The protected initialization does not authorize mass deletion. The normal bidirectional engine starts only after the reviewed result is verified and a safety baseline is saved."
            ),
            wrap=True,
            xalign=0,
            css_classes=["dim-label"],
        )
        self.review_content.append(assurance)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda _button: self.close())
        actions.append(cancel)
        self.apply_button = Gtk.Button(
            label=_("Apply Safe Initialization"),
            css_classes=["suggested-action"],
        )
        self.apply_button.set_sensitive(
            not analysis.has_blocking_errors
            and analysis.required_download_bytes <= analysis.free_bytes
        )
        self.apply_button.connect("clicked", self._apply)
        actions.append(self.apply_button)
        self.review_content.append(actions)

    @staticmethod
    def _path_preview(analysis: BootstrapAnalysis) -> str:
        lines: list[str] = []
        categories = (
            (_("Computer only"), analysis.local_only),
            (_("Nextcloud only"), analysis.remote_only),
            (_("Conflict"), tuple(conflict.path for conflict in analysis.conflicts)),
        )
        for label, paths in categories:
            for path in paths[:25]:
                lines.append(f"{label}: {path}")
            if len(paths) > 25:
                lines.append(
                    _("{label}: and {count} more…").format(
                        label=label, count=len(paths) - 25
                    )
                )
        return "\n".join(lines)

    def _policy_changed(self, row: Adw.ComboRow, _parameter: object) -> None:
        selected = int(row.get_selected())
        row.set_subtitle(POLICY_OPTIONS[selected][2])
        self.conflict_group.set_visible(POLICY_OPTIONS[selected][0] == BootstrapPolicy.REVIEW)

    def _apply(self, _button: Gtk.Button) -> None:
        if not self.analysis or not self.password:
            return
        selected = int(self.policy_row.get_selected()) if self.policy_row else 0
        policy = POLICY_OPTIONS[selected][0]
        decisions: dict[str, BootstrapPolicy] = {}
        if policy == BootstrapPolicy.REVIEW:
            values = (
                BootstrapPolicy.MERGE_NEWEST,
                BootstrapPolicy.NEXTCLOUD_FIRST,
                BootstrapPolicy.COMPUTER_FIRST,
            )
            decisions = {
                path: values[int(row.get_selected())]
                for path, row in self.conflict_rows.items()
            }
        analysis = self.analysis
        self._applying = self._working = True
        self.stack.set_visible_child_name("progress")
        self._start_updates()

        def begin(remote_etag: str | None, _used: int | None) -> None:
            if self.completed:
                return
            if analysis.resumed and remote_etag is None:
                self._working = False
                self._stop_updates()
                self.stack.set_visible_child_name("review")
                dialog = Adw.AlertDialog(
                    heading=_("Could Not Check the Saved Copy"),
                    body=_("Try applying the merge again when Nextcloud is available, or download a new copy."),
                )
                dialog.add_response("close", _("Close"))
                dialog.set_close_response("close")
                dialog.present(self)
                return
            self._set_progress(BootstrapProgress(_("Applying the reviewed safe initialization…")))
            try:
                self.runner.execute(
                    analysis,
                    self.password,
                    policy,
                    decisions,
                    self._queue_progress,
                    lambda result, failure: GLib.idle_add(
                        self._execution_ready, result, failure
                    ),
                    remote_etag=remote_etag,
                )
                self._worker_started = True
            except Exception as exc:
                self._show_error(str(exc))

        if analysis.resumed:
            self._set_progress(BootstrapProgress(_("Checking the Nextcloud folder…")))
            self._request_properties(begin)
        else:
            begin(None, None)

    def _execution_ready(
        self,
        result: BootstrapResult | None,
        error: Exception | None,
    ) -> bool:
        if self.completed:
            return GLib.SOURCE_REMOVE
        self._working = self._worker_started = False
        self._stop_updates()
        if error or not result:
            if self._exit_after_work:
                self.get_application().quit()
            else:
                self._show_error(
                    str(error or _("The safe initialization returned no result.")),
                    restart=True,
                )
        else:
            self.completed = True
            self.password = ""
            self.set_visible(False)
            self.on_complete()
        return GLib.SOURCE_REMOVE

    def _show_error(
        self, message: str, *, credential_missing: bool = False, restart: bool = False,
    ) -> None:
        self._working = self._worker_started = False
        self._stop_updates()
        self.spinner.set_spinning(False)
        self.error_label.set_text(self.logger.redactor.redact(message))
        self._record_log(message)
        if self.details_button.get_active():
            self._render_details()
        self._retry_fresh = restart
        self.retry_button.set_label(_("Start a New Analysis") if restart else _("Try Again"))
        self.retry_button.set_visible(not credential_missing)
        self.reconnect_button.set_visible(credential_missing)
        self.stack.set_visible_child_name("error")

    @property
    def exit_requested(self) -> bool:
        return self._exit_after_work

    def request_exit(self) -> bool:
        if not self._worker_started:
            return False
        self._exit_after_work = True
        if not self._applying:
            self._request_pause()
        return True

    def dispose_operation(self) -> None:
        self.completed = True
        self.password = ""
        self._stop_updates()
        if self._properties_request:
            self._properties_request.cancel()
            self._properties_request = None
        self.runner.cancel()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if self.completed:
            return False
        application = self.get_application()
        if not self._worker_started:
            self.dispose_operation()
            application.quit()
            return False
        dialog = Adw.AlertDialog(
            heading=_("Protected Synchronization in Progress"),
            body=_("The operation can continue in the background. If you quit, the app waits for a safe stopping point."),
        )
        dialog.add_response("cancel", _("Keep Open"))
        dialog.add_response("hide", _("Continue in Background"))
        dialog.add_response(
            "quit", _("Finish and Quit") if self._applying else _("Pause and Quit")
        )
        dialog.set_close_response("cancel")
        dialog.set_default_response("cancel")

        def chosen(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "hide":
                self.set_visible(False)
            elif response == "quit" and not self.request_exit():
                application.quit()

        dialog.connect("response", chosen)
        dialog.present(self)
        return True
