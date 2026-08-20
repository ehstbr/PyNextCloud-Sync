from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from pynextcloud_sync.util.i18n import _


class LogWindow(Adw.Window):
    MAX_BUFFER_LINES = 2_000
    TRIM_TO_LINES = 1_500

    def __init__(self, parent: Gtk.Window, app_logger: object) -> None:
        super().__init__(transient_for=parent, modal=False, title=_("Synchronization Log"))
        self.set_default_size(820, 560)
        self.logger = app_logger
        self.auto_scroll = True

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

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
        toolbar.set_content(scroller)

        action_bar = Gtk.ActionBar()
        auto = Gtk.CheckButton(label=_("Auto-scroll"), active=True)
        auto.connect("toggled", lambda row: setattr(self, "auto_scroll", row.get_active()))
        action_bar.pack_start(auto)
        copy_button = Gtk.Button(label=_("Copy"))
        copy_button.connect("clicked", self._copy)
        action_bar.pack_end(copy_button)
        folder_button = Gtk.Button(label=_("Open Log Folder"))
        folder_button.connect("clicked", self._open_folder)
        action_bar.pack_end(folder_button)
        toolbar.add_bottom_bar(action_bar)
        self.set_content(toolbar)

        self.unsubscribe = self.logger.subscribe(self._append)
        self.connect("close-request", self._closed)

    def _append(self, line: str) -> None:
        end = self.buffer.get_end_iter()
        prefix = "\n" if self.buffer.get_char_count() else ""
        self.buffer.insert(end, prefix + line)
        self._trim_buffer()
        if self.auto_scroll:
            GLib.idle_add(self._scroll_to_end)

    def _trim_buffer(self) -> None:
        line_count = self.buffer.get_line_count()
        if line_count <= self.MAX_BUFFER_LINES:
            return
        remove_lines = line_count - self.TRIM_TO_LINES
        start = self.buffer.get_start_iter()
        result = self.buffer.get_iter_at_line(remove_lines)
        end = result[-1] if isinstance(result, tuple) else result
        self.buffer.delete(start, end)

    def _scroll_to_end(self) -> bool:
        mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.view.scroll_mark_onscreen(mark)
        self.buffer.delete_mark(mark)
        return GLib.SOURCE_REMOVE

    def _copy(self, _button: Gtk.Button) -> None:
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, True)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

    def _open_folder(self, _button: Gtk.Button) -> None:
        self.logger.directory.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(self.logger.directory.as_uri(), None)

    def _closed(self, _window: Gtk.Window) -> bool:
        self.unsubscribe()
        return False
