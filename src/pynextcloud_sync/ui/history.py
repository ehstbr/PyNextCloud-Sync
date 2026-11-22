from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from pynextcloud_sync.nextcloud.activity import ActivityEvent
from pynextcloud_sync.storage.history import SyncHistory, SyncSummary
from pynextcloud_sync.util.i18n import _

from .activity import event_row, summary_row
from .log_view import LogView


class _RunRow(Adw.ExpanderRow):
    PAGE_SIZE = 50

    def __init__(
        self, summary: SyncSummary, history: SyncHistory, review: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.summary = summary
        self._history = history
        self._review = review
        self._rows: list[Gtk.ListBoxRow] = []
        self._limit = self.PAGE_SIZE
        self._loaded_count = -1
        self._loading = False
        self._more_row: Gtk.ListBoxRow | None = None
        summary_row(summary, self)
        self.connect("notify::expanded", self._expanded)

    def update(self, summary: SyncSummary) -> None:
        self.summary = summary
        if self.get_expanded():
            self._load_events()

    def _expanded(self, *_args: object) -> None:
        if self.get_expanded() and self._loaded_count != self.summary.event_count:
            self._load_events()

    def _load_events(self, offset: int = 0) -> None:
        if self._loading:
            return
        self._loading = True
        requested_count = self.summary.event_count
        limit = self._limit - offset
        self._history.details(
            self.summary.id, limit + 1,
            lambda events: self._render_events(events, requested_count, offset, limit),
            offset=offset,
        )

    def _render_events(
        self, events: list[ActivityEvent], requested_count: int, offset: int, limit: int,
    ) -> None:
        self._loading = False
        if not self.get_parent() or not self.get_expanded():
            self._loaded_count = -1
            return
        if requested_count != self.summary.event_count:
            self._load_events()
            return
        self._loaded_count = requested_count
        if offset == 0:
            for row in self._rows:
                self.remove(row)
            self._rows.clear()
        elif self._more_row:
            self.remove(self._more_row)
            self._rows.pop()
        self._more_row = None
        for event in events[:limit]:
            self._add_detail(event_row(event))
        if self.summary.outcome == "blocked":
            button = Gtk.Button(label=_("Review Safety Alert"), halign=Gtk.Align.CENTER)
            button.connect("clicked", lambda _button: self._review(self.summary.id))
            self._add_detail(self._button_row(button))
        if len(events) > limit:
            more = Gtk.Button(label=_("Show more events"), halign=Gtk.Align.CENTER)
            more.connect("clicked", self._load_more)
            self._more_row = self._button_row(more)
            self._add_detail(self._more_row)

    def _load_more(self, _button: Gtk.Button) -> None:
        if self._loading:
            return
        offset = self._limit
        self._limit += self.PAGE_SIZE
        self._load_events(offset)

    def _add_detail(self, row: Gtk.ListBoxRow) -> None:
        self.add_row(row)
        self._rows.append(row)

    @staticmethod
    def _button_row(button: Gtk.Button) -> Gtk.ListBoxRow:
        button.add_css_class("flat")
        button.set_margin_top(3)
        button.set_margin_bottom(3)
        return Gtk.ListBoxRow(child=button, activatable=False, selectable=False)


class _ActivityView(Gtk.ScrolledWindow):
    PAGE_SIZE = 40

    def __init__(
        self, history: SyncHistory, can_review: Callable[[str], bool],
        review: Callable[[str], None],
    ) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._history = history
        self._can_review = can_review
        self._review = review
        self._rows: dict[str, tuple[SyncSummary, Gtk.ListBoxRow]] = {}
        self._limit = self.PAGE_SIZE
        self._request = 0
        self._disposed = False
        self._scroll_anchor: tuple[float, float] | None = None

        self._list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self._list.set_header_func(self._set_date_header)
        empty = Gtk.Label(label=_("No synchronization activity yet"), css_classes=["dim-label"])
        empty.set_margin_top(18)
        empty.set_margin_bottom(18)
        empty.set_wrap(True)
        self._list.set_placeholder(empty)
        self._more = Gtk.Button(
            label=_("Show older synchronizations"), halign=Gtk.Align.CENTER, visible=False,
        )
        self._more.connect("clicked", self._load_older)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(18)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.append(self._list)
        content.append(self._more)
        clamp = Adw.Clamp(maximum_size=760, child=content)
        self.set_child(clamp)

        self.get_vadjustment().connect("changed", self._restore_scroll)
        self._unsubscribe = history.subscribe(self.refresh)
        self.refresh()

    @staticmethod
    def _set_date_header(row: Gtk.ListBoxRow, previous: Gtk.ListBoxRow | None) -> None:
        stamp = dt.datetime.fromtimestamp(row.sync_ended_at).date()
        if previous and stamp == dt.datetime.fromtimestamp(previous.sync_ended_at).date():
            row.set_header(None)
            return
        label = Gtk.Label(
            label=stamp.strftime("%x"), xalign=0, css_classes=["dim-label", "heading"],
        )
        label.set_margin_top(10)
        label.set_margin_bottom(4)
        label.set_margin_start(12)
        row.set_header(label)

    def refresh(self) -> None:
        self._request += 1
        request = self._request
        self._history.recent(self._limit + 1, lambda entries: self._render(request, entries))

    def _load_older(self, _button: Gtk.Button) -> None:
        self._limit += self.PAGE_SIZE
        self.refresh()

    def _render(self, request: int, entries: list[SyncSummary]) -> None:
        if self._disposed or request != self._request:
            return
        has_more = len(entries) > self._limit
        visible = entries[: self._limit]
        if has_more and entries[-1].id in self._rows:
            # A new run shifted the visible page down by one. Keep its old tail.
            visible = entries
            self._limit += 1
        ids = {entry.id for entry in visible}
        adjustment = self.get_vadjustment()
        if visible and self._rows and visible[0].id not in self._rows and adjustment.get_value() > 0:
            self._scroll_anchor = (adjustment.get_value(), adjustment.get_upper())
        for run_id in self._rows.keys() - ids:
            _, row = self._rows.pop(run_id)
            self._list.remove(row)

        for index, entry in enumerate(visible):
            expandable = entry.event_count > 0 or (
                entry.outcome == "blocked" and self._can_review(entry.id)
            )
            existing, row = self._rows.get(entry.id, (None, None))
            if row is not None and isinstance(row, _RunRow) == expandable:
                if entry != existing and isinstance(row, _RunRow):
                    row.update(entry)
                self._rows[entry.id] = (entry, row)
                continue
            if row is not None:
                self._list.remove(row)
            if expandable:
                row = _RunRow(entry, self._history, self._review)
            else:
                row = Adw.ActionRow(activatable=False)
                summary_row(entry, row)
            row.sync_ended_at = entry.ended_at
            self._list.insert(row, index)
            self._rows[entry.id] = (entry, row)
        self._more.set_visible(has_more)

    def _restore_scroll(self, adjustment: Gtk.Adjustment) -> None:
        if self._scroll_anchor is not None:
            value, upper = self._scroll_anchor
            self._scroll_anchor = None
            adjustment.set_value(value + max(0, adjustment.get_upper() - upper))

    def dispose_view(self) -> None:
        self._disposed = True
        self._unsubscribe()


class HistoryWindow(Adw.Window):
    def __init__(self, parent: Gtk.Window, history: SyncHistory, logger: object, scheduler: object) -> None:
        super().__init__(
            transient_for=parent, destroy_with_parent=True,
            title=_("Synchronization History"), default_width=720, default_height=560,
        )
        self._scheduler = scheduler
        self._stack = Gtk.Stack(vexpand=True)
        self.activity = _ActivityView(history, self._can_review, self._review)
        self.log = LogView(logger)
        self._stack.add_titled(self.activity, "activity", _("Activity"))
        self._stack.add_titled(self.log, "log", _("Detailed Log"))

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        back = Gtk.Button(label=_("Back"), css_classes=["flat"])
        back.connect("clicked", lambda _button: self.close())
        header.pack_start(back)
        toolbar.add_top_bar(header)
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        switcher = Gtk.StackSwitcher(stack=self._stack, halign=Gtk.Align.CENTER)
        switcher.set_margin_top(12)
        view.append(switcher)
        view.append(self._stack)
        toolbar.set_content(view)
        self.set_content(toolbar)
        self.connect("close-request", self._closed)

    def select_page(self, *, technical: bool) -> None:
        self._stack.set_visible_child_name("log" if technical else "activity")

    def _can_review(self, run_id: str) -> bool:
        return self._scheduler.safety_history_id == run_id and self._scheduler.safety_alert is not None

    def _review(self, run_id: str) -> None:
        parent = self.get_transient_for()
        if parent and self._can_review(run_id):
            application = parent.get_application()
            if application:
                application.review_safety_alert(self)

    def _closed(self, _window: Gtk.Window) -> bool:
        self.activity.dispose_view()
        self.log.dispose_log()
        return False
