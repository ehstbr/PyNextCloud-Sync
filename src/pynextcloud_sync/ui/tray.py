from __future__ import annotations

from pathlib import Path
from typing import Callable

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

from pynextcloud_sync.core.state import StateSnapshot
from pynextcloud_sync.ui.tray_state import TrayPresentation, presentation_for
from pynextcloud_sync.util.paths import project_root
from pynextcloud_sync.util.i18n import _


ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
    <method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
    <method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
    <method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
    <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  </interface>
</node>
"""


class StatusNotifier:
    """Small StatusNotifierItem implementation without a GTK3 helper process."""

    def __init__(
        self,
        state_controller: object,
        open_window: Callable[[], None],
        sync_now: Callable[[], None],
        toggle_pause: Callable[[], None],
        open_folder: Callable[[], None],
        open_log: Callable[[], None],
        open_settings: Callable[[], None],
        quit_app: Callable[[], None],
        logger: object,
    ) -> None:
        self.state_controller = state_controller
        self.actions = {
            1: open_window,
            2: sync_now,
            3: toggle_pause,
            4: open_folder,
            5: open_log,
            7: open_settings,
            8: quit_app,
        }
        self.logger = logger
        self.connection: Gio.DBusConnection | None = None
        self.item_registration = 0
        self.menu_registration = 0
        self.revision = 1
        self.snapshot = state_controller.snapshot
        self.application_icon = self._find_application_icon()
        self._pixmap_cache: dict[Path, list[tuple[int, int, bytes]]] = {}
        self._unsubscribe: Callable[[], None] | None = state_controller.subscribe(
            self._state_changed
        )

    def _icon_candidates(self) -> list[Path]:
        filename = "com.eduhcommerce.PyNextCloudSync.svg"
        return [
            project_root() / "data" / "icons" / filename,
            Path("/usr/share/icons/hicolor/scalable/apps") / filename,
            Path("/usr/local/share/icons/hicolor/scalable/apps") / filename,
        ]

    def _find_application_icon(self) -> Path | None:
        return next((path for path in self._icon_candidates() if path.is_file()), None)

    def _status_icon_candidates(self, icon_key: str) -> list[Path]:
        filename = f"pynextcloud-sync-status-{icon_key}-symbolic.svg"
        return [
            project_root() / "data" / "icons" / "status" / filename,
            Path("/usr/share/icons/hicolor/symbolic/status") / filename,
            Path("/usr/local/share/icons/hicolor/symbolic/status") / filename,
        ]

    def _find_status_icon(self, presentation: TrayPresentation) -> Path | None:
        return next(
            (
                path
                for path in self._status_icon_candidates(presentation.icon_key)
                if path.is_file()
            ),
            self.application_icon,
        )

    def _icon_data(
        self, presentation: TrayPresentation
    ) -> tuple[str, str, list[tuple[int, int, bytes]]]:
        source = self._find_status_icon(presentation)
        if not source:
            return "com.eduhcommerce.PyNextCloudSync", "", []
        pixmaps = self._pixmap_cache.get(source)
        if pixmaps is None:
            pixmaps = self._load_application_pixmaps(source)
            self._pixmap_cache[source] = pixmaps
        return str(source), str(source.parent), pixmaps

    def _load_application_pixmaps(
        self, source: Path | None
    ) -> list[tuple[int, int, bytes]]:
        """Provide a branded fallback when the tray host cannot resolve IconName."""

        if not source:
            return []
        result: list[tuple[int, int, bytes]] = []
        try:
            for size in (16, 22, 32):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(source), size, size, True
                )
                pixels = pixbuf.get_pixels()
                channels = pixbuf.get_n_channels()
                rowstride = pixbuf.get_rowstride()
                has_alpha = pixbuf.get_has_alpha()
                argb = bytearray()
                for y in range(pixbuf.get_height()):
                    for x in range(pixbuf.get_width()):
                        offset = y * rowstride + x * channels
                        red, green, blue = pixels[offset : offset + 3]
                        alpha = pixels[offset + 3] if has_alpha else 255
                        argb.extend((alpha, red, green, blue))
                result.append((pixbuf.get_width(), pixbuf.get_height(), bytes(argb)))
        except GLib.Error as exc:
            self.logger.warning("Could not create the tray icon fallback: %s", exc)
            return []
        return result

    def start(self) -> None:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
            menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
            self.item_registration = self.connection.register_object(
                "/StatusNotifierItem", item_info, self._item_method, self._item_property
            )
            self.menu_registration = self.connection.register_object(
                "/MenuBar", menu_info, self._menu_method, self._menu_property
            )
            self.connection.call(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", ("/StatusNotifierItem",)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._registered,
                None,
            )
        except GLib.Error as exc:
            self.logger.warning("System tray host is unavailable: %s", exc)

    def stop(self) -> None:
        if self.connection:
            for registration in (self.item_registration, self.menu_registration):
                if registration:
                    self.connection.unregister_object(registration)
        self.item_registration = self.menu_registration = 0
        self.connection = None
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self._pixmap_cache.clear()

    def _registered(self, connection: Gio.DBusConnection, result: Gio.AsyncResult, _data: object) -> None:
        try:
            connection.call_finish(result)
            self.logger.info("StatusNotifierItem registered with the tray host.")
        except GLib.Error as exc:
            self.logger.warning("No compatible tray host accepted the indicator: %s", exc)

    def _item_property(
        self, _connection: Gio.DBusConnection, _sender: str, _path: str, _interface: str, name: str
    ) -> GLib.Variant:
        presentation = presentation_for(self.snapshot.state)
        icon_name, icon_theme_path, icon_pixmaps = self._icon_data(presentation)
        state_label = _(presentation.label)
        title = _("PyNextCloud Sync — {state}").format(state=state_label)
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "pynextcloud-sync"),
            "Title": GLib.Variant("s", title),
            "Status": GLib.Variant("s", presentation.status),
            "WindowId": GLib.Variant("i", 0),
            # GNOME's AppIndicator host runs outside this process. An absolute
            # path prevents it from losing the icon when the app is launched
            # directly from the ZIP and its icon theme is not installed yet.
            "IconThemePath": GLib.Variant("s", icon_theme_path),
            "IconName": GLib.Variant("s", icon_name),
            "IconPixmap": GLib.Variant("a(iiay)", icon_pixmaps),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionIconName": GLib.Variant("s", icon_name),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", icon_pixmaps),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)",
                (
                    icon_name,
                    icon_pixmaps,
                    title,
                    self.snapshot.message or state_label,
                ),
            ),
            # GNOME AppIndicator hosts use this to open the exported menu on one click.
            "ItemIsMenu": GLib.Variant("b", True),
            "Menu": GLib.Variant("o", "/MenuBar"),
        }
        return values[name]

    def _item_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        method: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "Activate":
            self.actions[1]()
        elif method == "SecondaryActivate":
            self.actions[2]()
        invocation.return_value(None)

    def _menu_property(
        self, _connection: Gio.DBusConnection, _sender: str, _path: str, _interface: str, name: str
    ) -> GLib.Variant:
        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", self._icon_theme_paths()),
        }
        return values[name]

    def _icon_theme_paths(self) -> list[str]:
        candidates = [
            project_root() / "data" / "icons" / "status",
            Path("/usr/share/icons/hicolor/symbolic/status"),
            Path("/usr/local/share/icons/hicolor/symbolic/status"),
        ]
        return [str(path) for path in candidates if path.is_dir()]

    def _properties(self, item_id: int) -> dict[str, GLib.Variant]:
        presentation = presentation_for(self.snapshot.state)
        paused = presentation.user_paused
        safety_review = self.snapshot.state.value == "safety_review"
        labels = {
            0: "PyNextCloud Sync",
            1: _("Open PyNextCloud Sync"),
            2: _("Review Safety Alert") if safety_review else (_("Sync Once") if paused else _("Sync Now")),
            3: _("Resume Sync") if paused else _("Pause Sync"),
            4: _("Open NextCloud Folder"),
            5: _("View Sync Log"),
            6: "",
            7: _("Settings"),
            8: _("Quit"),
        }
        if item_id == 0:
            return {}
        properties: dict[str, GLib.Variant] = {
            "label": GLib.Variant("s", labels[item_id]),
            "enabled": GLib.Variant("b", True),
            "visible": GLib.Variant("b", True),
        }
        if item_id == 6:
            properties["type"] = GLib.Variant("s", "separator")
        icon_names = {
            1: "window-new-symbolic",
            2: "security-high-symbolic" if safety_review else "emblem-synchronizing-symbolic",
            3: "media-playback-start-symbolic" if paused else "media-playback-pause-symbolic",
            4: "folder-symbolic",
            5: "text-x-generic-symbolic",
            7: "emblem-system-symbolic",
            8: "application-exit-symbolic",
        }
        if item_id in icon_names:
            properties["icon-name"] = GLib.Variant("s", icon_names[item_id])
        return properties

    def _layout_data(
        self, item_id: int
    ) -> tuple[int, dict[str, GLib.Variant], list[GLib.Variant]]:
        children: list[GLib.Variant] = []
        if item_id == 0:
            children = [
                GLib.Variant("(ia{sv}av)", self._layout_data(child))
                for child in range(1, 9)
            ]
        return item_id, self._properties(item_id), children

    def _menu_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        method: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        values = parameters.unpack()
        if method == "GetLayout":
            invocation.return_value(
                GLib.Variant(
                    "(u(ia{sv}av))", (self.revision, self._layout_data(0))
                )
            )
        elif method == "GetGroupProperties":
            ids = values[0] or list(range(9))
            result = [(item_id, self._properties(item_id)) for item_id in ids if 0 <= item_id <= 8]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = values
            value = self._properties(item_id).get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event_id, _data, _timestamp = values
            if event_id == "clicked" and item_id in self.actions:
                self.actions[item_id]()
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event_id, _data, _timestamp in values[0]:
                if event_id == "clicked" and item_id in self.actions:
                    self.actions[item_id]()
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))

    def _state_changed(self, snapshot: StateSnapshot) -> None:
        self.snapshot = snapshot
        self.revision += 1
        if not self.connection:
            return
        try:
            presentation = presentation_for(snapshot.state)
            changed_names = (
                "Title",
                "Status",
                "IconThemePath",
                "IconName",
                "IconPixmap",
                "AttentionIconName",
                "AttentionIconPixmap",
                "ToolTip",
            )
            changed = {
                name: self._item_property(None, "", "", "", name)
                for name in changed_names
            }
            self.connection.emit_signal(
                None,
                "/StatusNotifierItem",
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                GLib.Variant(
                    "(sa{sv}as)",
                    ("org.kde.StatusNotifierItem", changed, []),
                ),
            )
            self.connection.emit_signal(
                None,
                "/StatusNotifierItem",
                "org.kde.StatusNotifierItem",
                "NewStatus",
                GLib.Variant("(s)", (presentation.status,)),
            )
            for signal_name in (
                "NewTitle",
                "NewIcon",
                "NewAttentionIcon",
                "NewToolTip",
            ):
                self.connection.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.kde.StatusNotifierItem",
                    signal_name,
                    None,
                )
            self.connection.emit_signal(
                None,
                "/MenuBar",
                "com.canonical.dbusmenu",
                "LayoutUpdated",
                GLib.Variant("(ui)", (self.revision, 0)),
            )
        except GLib.Error:
            pass
