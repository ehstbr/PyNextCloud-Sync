from __future__ import annotations

import datetime as dt

from gi.repository import Adw, Gtk

from pynextcloud_sync.nextcloud.activity import ActivityEvent
from pynextcloud_sync.storage.history import SyncSummary
from pynextcloud_sync.util.i18n import _, ngettext


_OUTCOMES = {
    "completed": (_("Synchronization completed"), "pynextcloud-sync-emblem-ok-symbolic", "success"),
    "conflict": (_("Synchronization completed with conflicts"), "pynextcloud-sync-dialog-warning-symbolic", "warning"),
    "failed": (_("Synchronization failed"), "pynextcloud-sync-dialog-error-symbolic", "error"),
    "interrupted": (_("Synchronization interrupted"), "pynextcloud-sync-media-playback-pause-symbolic", "warning"),
    "blocked": (_("Synchronization blocked for safety"), "pynextcloud-sync-security-high-symbolic", "warning"),
}

_FILE_EVENTS = {
    "download": (_("Downloaded"), "pynextcloud-sync-go-down-symbolic"),
    "upload": (_("Uploaded"), "pynextcloud-sync-go-up-symbolic"),
    "remove": (_("Removed"), "pynextcloud-sync-user-trash-symbolic"),
    "rename": (_("Moved or renamed"), "pynextcloud-sync-document-open-recent-symbolic"),
    "mkdir": (_("Folder created"), "pynextcloud-sync-folder-symbolic"),
}


def _summary_text(entry: SyncSummary) -> str:
    parts = []
    if entry.downloads:
        parts.append("↓ " + ngettext(
            "{count} file downloaded", "{count} files downloaded", entry.downloads,
        ).format(count=entry.downloads))
    if entry.uploads:
        parts.append("↑ " + ngettext(
            "{count} file uploaded", "{count} files uploaded", entry.uploads,
        ).format(count=entry.uploads))
    if entry.removals:
        parts.append(ngettext(
            "{count} deletion", "{count} deletions", entry.removals,
        ).format(count=entry.removals))
    if entry.renames:
        parts.append(ngettext(
            "{count} item moved or renamed", "{count} items moved or renamed", entry.renames,
        ).format(count=entry.renames))
    if entry.folders_created:
        parts.append(ngettext(
            "{count} folder created", "{count} folders created", entry.folders_created,
        ).format(count=entry.folders_created))
    other_changes = entry.other_changes - entry.removals - entry.renames - entry.folders_created
    if other_changes > 0:
        parts.append(ngettext(
            "{count} other change", "{count} other changes", other_changes,
        ).format(count=other_changes))

    if entry.reason:
        parts.append(entry.reason)
    elif entry.outcome == "completed" and not parts:
        return (
            _("No files needed synchronization")
            if entry.complete else _("No file transfers recorded")
        )
    elif entry.outcome == "failed" and entry.exit_code is not None:
        parts.append(_("Exit code {code}. See the detailed log.").format(code=entry.exit_code))
    elif entry.outcome == "completed" and not entry.complete:
        parts.insert(0, _("Recorded file activity"))
    elif entry.outcome == "conflict":
        parts.append(_("See the detailed log for conflicts."))
    return " · ".join(parts)


def _time_label(value: float, *, seconds: bool = False) -> Gtk.Label:
    stamp = dt.datetime.fromtimestamp(value)
    label = Gtk.Label(
        label=stamp.strftime("%H:%M:%S" if seconds else "%H:%M"),
        valign=Gtk.Align.CENTER, css_classes=["dim-label", "numeric"],
    )
    label.set_tooltip_text(stamp.strftime("%x %H:%M:%S"))
    return label


def summary_row(entry: SyncSummary, row: Adw.ActionRow | Adw.ExpanderRow) -> None:
    title, icon, style = _OUTCOMES[entry.outcome]
    row.set_use_markup(False)
    row.set_title(title)
    row.set_subtitle(_summary_text(entry))
    image = Gtk.Image(icon_name=icon, css_classes=[style])
    row.add_prefix(image)
    row.add_suffix(_time_label(entry.ended_at))


def event_row(event: ActivityEvent) -> Adw.ActionRow:
    if event.kind in _FILE_EVENTS:
        action, icon = _FILE_EVENTS[event.kind]
        folder, _slash, title = event.detail.rpartition("/")
        subtitle = f"{action} · {folder}" if folder else action
    elif event.kind == "baseline":
        title, subtitle, icon = (
            _("Safety baseline updated"),
            _("A reference of local files was saved to detect unexpected deletions."),
            "pynextcloud-sync-security-high-symbolic",
        )
    else:
        title, subtitle, icon = (
            _("Safety baseline could not be updated"),
            _("See the detailed log for the safety baseline error."),
            "pynextcloud-sync-dialog-warning-symbolic",
        )
    child = Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False)
    image = Gtk.Image(icon_name=icon)
    if event.kind in {"download", "upload"}:
        image.add_css_class("accent")
    child.add_prefix(image)
    child.add_suffix(_time_label(event.at, seconds=True))
    if event.detail:
        child.set_tooltip_text(event.detail)
    return child
