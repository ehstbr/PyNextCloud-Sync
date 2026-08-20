from __future__ import annotations

from html import escape

from pynextcloud_sync.util.i18n import _


def terms_text() -> str:
    return _(
        "PyNextCloud Sync is an independent, unofficial third-party project. "
        "It is not affiliated with, sponsored by, endorsed by, maintained by, or "
        "otherwise connected to Nextcloud GmbH. Nextcloud is a registered trademark "
        "of Nextcloud GmbH.\n\n"
        "Bidirectional synchronization can upload, download, replace, conflict, or "
        "delete files on both the computer and the configured server. Use this "
        "software entirely at your own risk, test it with non-critical data, and "
        "maintain independent, restorable backups. The authors and contributors are "
        "not responsible for lost, corrupted, deleted, or otherwise damaged data.\n\n"
        "The application delegates file reconciliation and conflict handling to "
        "nextcloudcmd. Availability of notify_push and other server features depends "
        "on the Nextcloud installation. This release was tested with Nextcloud Hub 26 "
        "Spring (34.0.1) on Nextcloud AIO. Compatibility with other or future "
        "Nextcloud versions is not guaranteed.\n\n"
        "No telemetry, advertising, or usage tracking is included. Credentials are "
        "stored through the desktop Secret Service. Use of this software is also "
        "subject to the GNU General Public License version 3 or later and its "
        "warranty disclaimer."
    )


def release_notes_markup() -> str:
    sections = [
        (
            _("Version 0.1.32"),
            [
                _("Local mass-deletion safety alerts use urgent GNOME desktop notifications."),
                _("The notification opens the safety review directly through its Review Now action."),
                _("The alert explains that synchronization paused before local deletions could reach Nextcloud."),
                _("Resolved or obsolete safety notifications are removed automatically."),
            ],
        ),
        (
            _("Version 0.1.31"),
            [
                _("Account, storage, and server details are persisted and shown immediately when windows open."),
                _("Remote identity and server information refresh once when the application process starts."),
                _("Only storage usage refreshes after each successful synchronization."),
                _("Opening Home or Settings no longer causes another authenticated quota request."),
                _("Account and server information can still be refreshed manually from Settings."),
            ],
        ),
        (
            _("Version 0.1.30"),
            [
                _("Defined quotas show their occupied percentage inside the progress bar."),
                _("Unlimited quotas use a static empty bar with a centered infinity symbol."),
                _("Loading and unavailable storage states no longer animate the progress bar."),
            ],
        ),
        (
            _("Version 0.1.29"),
            [
                _("Temporary HTTP 429 validation limits preserve and retry the same new authorization."),
                _("Validated account details are reused after reconnection without an immediate duplicate authenticated request."),
                _("Temporary account-information failures are no longer described as requiring reconnection."),
                _("Storage usage is shown on the main window for bounded and unlimited quotas."),
            ],
        ),
        (
            _("Version 0.1.28"),
            [
                _("Replaced the oversized reconnect status page with a compact native header."),
                _("Prevented reconnect titles, descriptions, and account rows from overlapping."),
                _("Kept account details and browser authorization visible without internal scrolling."),
            ],
        ),
        (
            _("Version 0.1.27"),
            [
                _("Added a dedicated Account settings page with account, authorization, local folder, quota, and server information."),
                _("New browser authorizations use a stable per-computer name without the application version."),
                _("Revoked authorizations can be renewed without resetting the local folder, synchronization preferences, or safety baseline."),
                _("Authentication rejection remains blocked until the account is explicitly reconnected."),
            ],
        ),
        (
            _("Version 0.1.26"),
            [
                _("Credential lookup no longer preloads every Secret Service collection item."),
                _("Credentials are located by an exact D-Bus search including server, username, and schema."),
                _("Matching paths are loaded individually so an orphaned legacy item cannot block a valid credential."),
            ],
        ),
        (
            _("Version 0.1.25"),
            [
                _("Fixed false credential verification failures caused by a cached pre-write Secret Service view."),
                _("Successful keyring writes are now verified through a fresh Secret Service connection."),
                _("Setup remains blocked if the exact stored credential still cannot be read back."),
            ],
        ),
        (
            _("Version 0.1.24"),
            [
                _("Fixed the dead-end safety-analysis screen shown when no stored account credential exists."),
                _("Authentication failures now offer Reconnect Account instead of repeating an impossible credential lookup."),
                _("Returning to account login preserves the selected local folder and every file inside it."),
            ],
        ),
        (
            _("Version 0.1.23"),
            [
                _("New credentials use a versioned Secret Service schema so an orphaned legacy item cannot intercept replacement writes."),
                _("Healthy legacy credentials remain readable and both schema versions are cleared when an account is removed."),
                _("Every successful keyring write is verified by reading the credential back before setup continues."),
            ],
        ),
        (
            _("Version 0.1.22"),
            [
                _("Matching GNOME Keyring items are now loaded individually so an orphaned D-Bus path cannot hide a valid credential."),
                _("Credential search now checks every matching item and skips stale entries safely."),
                _("If no valid credential remains, the application requests authentication instead of repeatedly exposing an internal D-Bus error."),
            ],
        ),
        (
            _("Version 0.1.21"),
            [
                _("Fixed repeated credential failures caused by stale GNOME Keyring D-Bus item paths."),
                _("Credential lookup now reconnects to Secret Service and retries once when the referenced item no longer exists."),
                _("The recovery is bounded to one retry and preserves unrelated keyring error reporting."),
            ],
        ),
        (
            _("Version 0.1.20"),
            [
                _("Fixed the false locked-keyring state after a successful native GNOME Keyring unlock prompt."),
                _("Credential lookup now verifies the unlock by loading the stored secret instead of trusting a potentially stale D-Bus property."),
                _("Added compatibility and regression coverage for PyGObject unlock return variants while preserving canceled-prompt behavior."),
            ],
        ),
        (
            _("Version 0.1.19"),
            [
                _("Relicensed PyNextCloud Sync under the GNU General Public License version 3 or later."),
                _("About now identifies and displays the GPLv3 license using GTK's native license presentation."),
                _("Updated project, Debian, AppStream, documentation, terms, and translation metadata to consistently identify the new license."),
            ],
        ),
        (
            _("Version 0.1.18"),
            [
                _("Recovered explicitly from Linux inotify queue overflow by rebuilding filesystem monitoring and requesting a protected nextcloudcmd reconciliation."),
                _("Added a durable marker around nextcloudcmd that is cleared only after a successful safety baseline commit."),
                _("Retained the previous last-known-good safety baseline after interrupted runs."),
            ],
        ),
        (
            _("Version 0.1.17"),
            [
                _("Automatic update notices now wait until the main window is fully mapped before they are created."),
                _("Update windows are no longer reassociated after becoming visible, preventing placement on another monitor at the desktop origin."),
                _("Mandatory updates now show only Download New Version and Close Application."),
            ],
        ),
        (
            _("Version 0.1.16"),
            [
                _("The update notice now remains above the main window when the application is opened from its launcher."),
                _("Download and dismissal actions remain visible above the scrollable release details."),
                _("Download New Version now opens the latest GitHub release directly."),
                _("Mandatory updates use an urgent warning presentation and keep Not Now disabled."),
            ],
        ),
        (
            _("Version 0.1.15"),
            [
                _("Added automatic startup update checks through a validated GitHub version manifest."),
                _("Optional updates remain non-blocking, while mandatory updates prevent the synchronization runtime from starting."),
                _("Added a manual update check in About, semantic version comparison, safe failure handling, and UTC release dates."),
                _("The update window now shows a short summary and an expandable full changelog."),
            ],
        ),
        (
            _("Version 0.1.14"),
            [
                _("Added a protected first synchronization with a fresh isolated server snapshot and an explicit merge review."),
                _("Existing synchronization databases are archived and never silently reused during initialization."),
                _("Added a persistent safety baseline that blocks missing, replaced, empty, unreadable, or abnormally reduced local folders before nextcloudcmd starts."),
                _("Added safe recovery, one-time deletion approval, preserved conflict copies, and configurable review thresholds."),
            ],
        ),
        (
            _("Version 0.1.13"),
            [
                _("The default GNOME password collection is now unlocked before searching for the Nextcloud credential after biometric login."),
                _("A locked Login collection is no longer misreported as a missing stored credential during desktop autostart."),
                _("Added diagnostic logging and a regression test for credentials hidden while the keyring is locked."),
            ],
        ),
        (
            _("Version 0.1.12"),
            [
                _("Fixed Debian upgrade detection by querying the live D-Bus owner instead of treating list-apps as a process list."),
                _("The package now confirms that the old instance has exited before replacing application files."),
                _("Replaced the inaccurate package-upgrade fixture with a regression test that matches the real GLib behavior."),
            ],
        ),
        (
            _("Version 0.1.11"),
            [
                _("Fixed detection of running application instances during Debian upgrades when APT/dpkg does not preserve SUDO_UID."),
                _("Upgrades now stop and restart the application through its real per-user D-Bus session."),
                _("Added an executable regression test for graceful package-upgrade shutdown and restart."),
            ],
        ),
        (
            _("Version 0.1.10"),
            [
                _("Added the native GNOME Keyring unlock prompt required after biometric desktop login."),
                _("Canceled unlocks now remain separate from invalid Nextcloud credentials without repeated automatic prompts."),
                _("File synchronization and notify_push resume together after the keyring is unlocked."),
                _("Interactive Debian upgrades now gracefully stop and restart a running application."),
            ],
        ),
        (
            _("Version 0.1.9"),
            [
                _("Published the corrected website, source, issue, and changelog links under the canonical repository."),
            ],
        ),
        (
            _("Version 0.1.8"),
            [
                _("Added native Files sidebar and desktop shortcuts for the synchronized folder."),
                _("Added a branded folder icon and settings for all three desktop integrations."),
                _("Removing the Files bookmark outside the application now updates Settings without recreating it."),
            ],
        ),
        (
            _("Version 0.1.7"),
            [
                _("Settings now opens independently from the tray without opening the main window."),
                _("The independent Settings window is released after closing to preserve the low-memory interface lifecycle."),
            ],
        ),
        (
            _("Version 0.1.6"),
            [
                _("Fixed opening Settings from the tray while the main window is closed."),
                _("Reduced background memory by creating the main interface only when needed and releasing it when closed."),
                _("Bounded command output, log display, activity history, and browser login polling."),
                _("Avoided unnecessary filesystem watcher and push connection reconfiguration."),
            ],
        ),
        (
            _("Version 0.1.5"),
            [
                _("Activity messages can now be expanded with one click and copied from a right-click menu."),
                _("Fixed Brazilian Portuguese loading and completed the application translation catalog."),
            ],
        ),
        (
            _("Version 0.1.4"),
            [
                _("Made the tray icon and details follow synchronization state changes live."),
                _("Added compatible StatusNotifierItem and D-Bus property change notifications."),
            ],
        ),
        (
            _("Version 0.1.3"),
            [
                _("Fixed the application icon displayed by GNOME tray hosts."),
                _("Added icon theme, absolute SVG, and pixel fallback support."),
            ],
        ),
        (
            _("Version 0.1.2"),
            [
                _("A more compact, responsive main window with a stable status header."),
                _("Collapsible recent activity with severity icons and single-line messages."),
                _("A working one-click tray menu and more reliable window presentation."),
                _("Optional daily log files with configurable retention."),
                _("Expanded About, legal terms, license, credits, and changelog information."),
                _("Fixed D-Bus menu variants, literal log rendering, and numeric log formatting."),
            ],
        ),
        (
            _("Version 0.1.1"),
            [
                _("Fixed GNOME Keyring compatibility for saving, reading, and removing credentials."),
                _("Moved Keyring operations away from the GTK main thread."),
            ],
        ),
        (
            _("Version 0.1.0"),
            [
                _("Initial development release with browser login, nextcloudcmd synchronization, inotify, timers, notify_push, exclusions, logs, and GNOME integration."),
            ],
        ),
    ]
    parts: list[str] = []
    for heading, entries in sections:
        parts.append(f"<p>{escape(heading)}</p>")
        parts.append("<ul>")
        parts.extend(f"<li>{escape(entry)}</li>" for entry in entries)
        parts.append("</ul>")
    return "".join(parts)
