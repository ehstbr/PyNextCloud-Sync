from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from pynextcloud_sync.core.bootstrap import (
    BootstrapAnalysis,
    BootstrapPolicy,
    BootstrapResult,
    BootstrapRunner,
)
from pynextcloud_sync.util.i18n import _


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
        self.runner = BootstrapRunner(config, logger)
        self.analysis: BootstrapAnalysis | None = None
        self.password = ""
        self.completed = False
        self.conflict_rows: dict[str, Adw.ComboRow] = {}

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=200,
        )
        toolbar.set_content(self.stack)
        self.set_content(toolbar)
        self._build_progress_page()
        self._build_review_page()
        self._build_error_page()
        self.stack.set_visible_child_name("progress")
        self.connect("close-request", self._on_close_request)
        GLib.idle_add(self._begin_analysis)

    def _build_progress_page(self) -> None:
        page = Adw.StatusPage(
            icon_name="security-high-symbolic",
            title=_("Analyzing both sides safely"),
            description=_(
                "Automatic synchronization is blocked. PyNextCloud Sync is creating an isolated server snapshot before any decision is applied."
            ),
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        page.set_child(box)
        self.spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        box.append(self.spinner)
        self.progress_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        box.append(self.progress_label)
        self.stack.add_named(page, "progress")

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
        self.retry_button.connect("clicked", lambda _button: self._restart_analysis())
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

    def _begin_analysis(self) -> bool:
        self.stack.set_visible_child_name("progress")
        self.spinner.set_spinning(True)
        self.progress_label.set_text(_("Unlocking the account credential…"))
        account = self.config.data["account"]

        def secret_ready(password: str | None, error: Exception | None) -> None:
            if error or not password:
                self._show_error(
                    str(error or _("No stored credential was found for this account.")),
                    credential_missing=not error,
                )
                return
            self.password = password
            self.logger.add_secret(password)
            try:
                self.runner.analyze(
                    password,
                    lambda message: GLib.idle_add(self._set_progress, message),
                    lambda analysis, failure: GLib.idle_add(
                        self._analysis_ready, analysis, failure
                    ),
                )
            except Exception as exc:
                self._show_error(str(exc))

        self.credentials.lookup(account["server_url"], account["login_name"], secret_ready)
        return GLib.SOURCE_REMOVE

    def _set_progress(self, message: str) -> bool:
        self.progress_label.set_text(_(message))
        return GLib.SOURCE_REMOVE

    def _analysis_ready(
        self,
        analysis: BootstrapAnalysis | None,
        error: Exception | None,
    ) -> bool:
        self.spinner.set_spinning(False)
        if error or not analysis:
            self._show_error(str(error or _("The safety analysis returned no result.")))
            return GLib.SOURCE_REMOVE
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
        self.stack.set_visible_child_name("progress")
        self.spinner.set_spinning(True)
        self.progress_label.set_text(_("Applying the reviewed safe initialization…"))
        try:
            self.runner.execute(
                self.analysis,
                self.password,
                policy,
                decisions,
                lambda message: GLib.idle_add(self._set_progress, message),
                lambda result, failure: GLib.idle_add(
                    self._execution_ready, result, failure
                ),
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _execution_ready(
        self,
        result: BootstrapResult | None,
        error: Exception | None,
    ) -> bool:
        self.spinner.set_spinning(False)
        if error or not result:
            self._show_error(str(error or _("The safe initialization returned no result.")))
            return GLib.SOURCE_REMOVE
        self.config.data["safety"]["bootstrap_complete"] = True
        self.config.data["safety"]["bootstrap_completed_at"] = (
            GLib.DateTime.new_now_utc().format_iso8601()
        )
        self.config.save()
        self.completed = True
        self.password = ""
        self.set_visible(False)
        self.on_complete()
        return GLib.SOURCE_REMOVE

    def _restart_analysis(self) -> None:
        self.runner.cancel()
        self.runner.cleanup(self.analysis)
        self.runner = BootstrapRunner(self.config, self.logger)
        self.analysis = None
        self.password = ""
        self._begin_analysis()

    def _show_error(self, message: str, *, credential_missing: bool = False) -> None:
        self.spinner.set_spinning(False)
        self.error_label.set_text(message)
        self.retry_button.set_visible(not credential_missing)
        self.reconnect_button.set_visible(credential_missing)
        self.stack.set_visible_child_name("error")

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if not self.completed:
            self.runner.cancel()
            self.runner.cleanup(self.analysis)
            self.password = ""
            application = self.get_application()
            if application:
                GLib.idle_add(application.quit)
        return False
