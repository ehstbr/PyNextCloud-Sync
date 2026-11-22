from __future__ import annotations

from collections import deque
from threading import Lock

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, Gtk

from pynextcloud_sync.util.i18n import _


class LogView(Gtk.Box):
    MAX_BUFFER_LINES = 2_000
    TRIM_TO_LINES = 1_500

    def __init__(self, app_logger: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.logger = app_logger
        self.auto_scroll = True
        self._pending: deque[str] = deque(maxlen=500)
        self._pending_lock = Lock()
        self._flush_source = 0
        self._disposed = False

        self.buffer = Gtk.TextBuffer()
        if hasattr(self.buffer, "set_enable_undo"):
            self.buffer.set_enable_undo(False)
        self.buffer.set_text(self.logger.tail(500))
        view = Gtk.TextView(
            buffer=self.buffer,
            editable=False,
            cursor_visible=False,
            monospace=True,
            left_margin=12,
            right_margin=12,
            top_margin=12,
            bottom_margin=12,
        )
        self.view = view
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(view)
        self._vertical = scroller.get_vadjustment()
        self._vertical.connect("changed", self._scroll_if_following)
        view.connect("map", self._scroll_if_following)
        self.append(scroller)

        action_bar = Gtk.ActionBar()
        auto = Gtk.CheckButton(label=_("Auto-scroll"), active=True)
        auto.connect("toggled", self._toggle_auto_scroll)
        action_bar.pack_start(auto)
        copy_button = Gtk.Button(label=_("Copy"))
        copy_button.connect("clicked", self._copy)
        action_bar.pack_end(copy_button)
        folder_button = Gtk.Button(label=_("Open Log Folder"))
        folder_button.connect("clicked", self._open_folder)
        action_bar.pack_end(folder_button)
        self.append(action_bar)

        self.unsubscribe = self.logger.subscribe(self._append)

    def _toggle_auto_scroll(self, button: Gtk.CheckButton) -> None:
        self.auto_scroll = button.get_active()
        if self.auto_scroll:
            self._scroll_to_end()

    def _append(self, line: str) -> None:
        with self._pending_lock:
            if self._disposed:
                return
            self._pending.append(line)
            if not self._flush_source:
                self._flush_source = GLib.timeout_add(150, self._flush)

    def _flush(self) -> bool:
        with self._pending_lock:
            lines = tuple(self._pending)
            self._pending.clear()
            self._flush_source = 0
        end = self.buffer.get_end_iter()
        prefix = "\n" if self.buffer.get_char_count() else ""
        self.buffer.insert(end, prefix + "\n".join(lines))
        self._trim_buffer()
        if self.auto_scroll and self.view.get_mapped():
            self._scroll_to_end()
        return GLib.SOURCE_REMOVE

    def _trim_buffer(self) -> None:
        line_count = self.buffer.get_line_count()
        if line_count <= self.MAX_BUFFER_LINES:
            return
        remove_lines = line_count - self.TRIM_TO_LINES
        start = self.buffer.get_start_iter()
        result = self.buffer.get_iter_at_line(remove_lines)
        end = result[-1] if isinstance(result, tuple) else result
        self.buffer.delete(start, end)

    def _scroll_to_end(self) -> None:
        self._vertical.set_value(self._vertical.get_upper() - self._vertical.get_page_size())

    def _scroll_if_following(self, *_args: object) -> None:
        if self.auto_scroll and self.view.get_mapped():
            self._scroll_to_end()

    def _copy(self, _button: Gtk.Button) -> None:
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, True)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

    def _open_folder(self, _button: Gtk.Button) -> None:
        self.logger.directory.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(self.logger.directory.as_uri(), None)

    def dispose_log(self) -> None:
        with self._pending_lock:
            self._disposed = True
            self._pending.clear()
            if self._flush_source:
                GLib.source_remove(self._flush_source)
                self._flush_source = 0
        self.unsubscribe()
