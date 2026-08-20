# Changelog

## 0.1.32 — 2026-08-15

- Raised local mass-deletion safety alerts as urgent GNOME desktop
  notifications.
- Added a **Review Now** notification action that opens the safety confirmation
  directly instead of only presenting the main window.
- Clarified that synchronization is paused before missing local files can be
  deleted from Nextcloud.
- Cleared resolved or obsolete safety notifications after approval, protected
  recovery, account removal, or runtime recreation.
- Kept deletion protection deliberately scoped to local changes before they
  are propagated to the server.

## 0.1.31 — 2026-08-14

- Persisted account identity, storage usage, and basic server information so
  Home and Settings can display the last known values immediately.
- Refresh display name, email, quota, Nextcloud product, and server version
  once when the application process starts, independently of window opening.
- Refresh and persist only storage usage after every successful
  synchronization, when the occupied quota is most representative.
- Kept **Refresh Account Information** as an explicit manual update for both
  account and server details.
- Removed credential and Nextcloud API requests caused solely by reopening the
  Home or Settings windows.
- Preserve the last known values when a background refresh is temporarily
  unavailable or rate limited.

## 0.1.30 — 2026-08-14

- Displayed the occupied percentage inside the progress bar for accounts with a
  defined storage quota.
- Replaced the animated unlimited-quota indicator with a static empty bar and a
  centered infinity symbol.
- Kept loading and unavailable storage states empty and motionless.

## 0.1.29 — 2026-08-14

- Preserved a newly created browser authorization when Nextcloud temporarily
  returns HTTP 429, retrying only its validation with progressive delays.
- Reused the account details returned by successful validation after
  reconnection, avoiding an immediate duplicate authenticated request.
- Stopped describing rate limits and other temporary account-information
  failures as requiring another reconnection.
- Added storage usage to the main window with a proportional progress bar for
  bounded quotas and an indeterminate state for server-storage-limited accounts.

## 0.1.28 — 2026-08-14

- Replaced the oversized reconnect status page with a compact native header.
- Fixed overlapping title, description, and account rows in the reconnection
  window at compact sizes.
- Kept the account details and browser authorization action visible without an
  internal scrolling region.

## 0.1.27 — 2026-08-14

- Added a dedicated **Account** page in Settings with the configured username,
  local folder, recorded Nextcloud authorization name, display name, email,
  storage quota, server product, server version, and availability status.
- New Login Flow authorizations use a stable per-computer name in the form
  `PyNextCloud-Sync (hostname)` instead of including the application version.
- Added an in-place reconnection flow that validates and replaces only the
  revoked credential while preserving the account configuration, local folder,
  synchronization preferences, and existing safety baseline.
- The account-attention card now links directly to the Account settings page,
  and its primary action changes to **Reconnect Account**.
- Authentication rejection is now retained as a blocking state, preventing
  automatic triggers from repeatedly retrying a revoked credential until the
  user reconnects the account.
- Reconnection verifies that the browser authorized the same server and user,
  confirms the new keyring write, reconnects push notifications, and resumes
  with a normal protected synchronization.

## 0.1.26 — 2026-08-14

- Fixed credential lookup being aborted while initializing Secret Service with
  `LOAD_COLLECTIONS` when the keyring contained any orphaned item path.
- The credential flow now opens only an encrypted session, resolves the default
  collection without preloading its items, and performs an exact D-Bus search
  including `xdg:schema`.
- Matching paths are loaded individually, so an unrelated orphaned legacy item
  cannot block a valid current credential.
- Validated the corrected flow against the reported live GNOME Keyring state.

## 0.1.25 — 2026-08-14

- Fixed false post-write verification failures caused by the process-wide
  Secret Service proxy retaining its pre-write search view.
- Credential storage now disconnects the cached proxy after a successful write
  and verifies the new item through a fresh Secret Service connection.
- The setup assistant still refuses to continue when a fresh connection cannot
  read back the exact stored credential.
- Added regression coverage for credentials that become visible only after the
  Secret Service proxy is renewed.

## 0.1.24 — 2026-08-14

- Fixed a dead end in the protected initial synchronization when no stored
  credential was available.
- The error page now replaces the ineffective retry action with **Reconnect
  Account** when authentication is required.
- Reconnecting closes and cleans up the safety analysis before returning to the
  account login flow, while preserving the selected local folder and its files.
- Added an executable lifecycle contract covering the recovery navigation.

## 0.1.23 — 2026-08-14

- Moved newly stored account credentials to a versioned Secret Service schema,
  preventing an orphaned legacy item from intercepting replacement writes.
- Preserved read compatibility with healthy credentials stored under the legacy
  schema and clear both schema versions when an account is removed.
- A successful keyring write is now immediately verified by reading the new
  credential back before account setup can continue.
- Added regression coverage for schema selection, legacy cleanup, and a keyring
  write that reports success without producing a readable item.

## 0.1.22 — 2026-08-14

- Fixed persistent `No such secret item` failures when a stale GNOME Keyring
  entry appeared alongside a newer valid credential.
- Credential search now requests every matching item without bulk-loading
  secrets, then loads each result individually and skips orphaned D-Bus paths.
- If no valid credential remains after one fresh lookup, the application now
  reports a missing credential and requests authentication instead of exposing
  the internal D-Bus error repeatedly.
- Added regression coverage for mixed stale/valid results and stale-only results.

## 0.1.21 — 2026-08-14

- Fixed repeated credential failures when GNOME Keyring returned a stale D-Bus
  object path for a secret item that had already been removed or replaced.
- The credential store now discards the cached Secret Service proxy and retries
  the lookup once with a fresh connection when this specific error occurs.
- The recovery is strictly bounded to one retry and does not hide unrelated
  Secret Service, authentication, or keyring-locking errors.
- Added regression coverage for both successful recovery and a persistent stale
  item failure.

## 0.1.20 — 2026-08-13

- Fixed a false locked-keyring state after a successful native GNOME Keyring
  prompt, most commonly seen after signing in to GNOME with biometrics.
- Credential lookup now verifies the unlock by loading the stored secret instead
  of trusting a potentially stale D-Bus `Locked` property.
- Added compatibility for additional PyGObject unlock return shapes and a
  regression test for a successful unlock reported with a zero count.
- A genuinely canceled unlock still remains in the dedicated locked-keyring
  state without repeated automatic prompts.

## 0.1.19 — 2026-08-11

- Relicensed PyNextCloud Sync under the GNU General Public License version 3
  or later.
- Replaced the custom MIT text in About with GTK's native GPLv3 license
  presentation.
- Updated Python, Debian, AppStream, documentation, terms, third-party notices,
  and translation metadata to identify the new license consistently.
- No synchronization, safety, authentication, update-checking, or desktop
  integration behavior was changed.

## 0.1.18 — 2026-08-10

- Detect Linux `IN_Q_OVERFLOW` explicitly. When the inotify queue loses events,
  discard trust in that event stream, rebuild the watcher, and request one
  protected normal reconciliation through `nextcloudcmd`.
- Add a minimal durable run marker before starting `nextcloudcmd`; clear it only
  after a successful run has produced and persisted a new safety baseline.
- If the wrapper is killed or otherwise interrupted, keep using the previous
  last-known-good baseline on restart. Existing folder identity, empty-tree,
  missing-database, and abnormal-deletion checks still run before `nextcloudcmd`.
- Keep the marker when the post-sync baseline cannot be committed instead of
  silently treating the wrapper state as fully recorded.
- Persist the safety manifest with a directory `fsync` after the atomic replace.
- Do not add a custom rescan, WebDAV diff, conflict resolver, transaction
  journal, or synchronization algorithm. File discovery, transfer, conflict
  handling, and deletion propagation remain the responsibility of `nextcloudcmd`.

## 0.1.17 — 2026-08-09

- Fixed automatic update notices opening on another monitor at the desktop
  origin when the application was launched normally.
- Startup notices now wait for the main window to be fully mapped and one UI
  cycle to complete before being created with that window as their transient
  parent, matching the correctly centered manual-check behavior.
- Removed the unsafe fallback that changed a visible update window's transient
  parent. A notice created during tray-only startup is recreated after the main
  window maps instead.
- Mandatory updates now show only **Download New Version** and
  **Close Application**. **Not Now** remains available only for optional
  updates.
- Added executable lifecycle tests for unmapped, already mapped, replaced, and
  temporarily unmapped parent windows.

## 0.1.16 — 2026-08-09

- Kept the update window above the main application window by assigning the
  visible application window as its transient parent and presenting the notice
  again after GTK completes a launcher activation.
- Moved the primary actions into a fixed hero area above the scrollable version
  details and changelog, so downloading or dismissing an optional update never
  requires scrolling.
- Renamed the main action to **Download New Version** and changed its fixed,
  trusted destination to the latest release page.
- Made mandatory notices visibly urgent with a warning icon and the explicit
  **Mandatory update available** heading.
- Mandatory notices keep **Not Now** visible but disabled, while preserving the
  required **Download New Version** and **Close Application** actions.

## 0.1.15 — 2026-08-09

- Added `version.json` at the repository root with a schema version, latest
  application version, mandatory-update flag, plain-text summary, and an ISO
  8601 release timestamp in UTC. A separate plain-text changelog list feeds an
  expandable release-details section in the update window.
- Added an automatic check at every process startup. The synchronization
  runtime, `inotify`, timers, and `notify_push` remain inactive until the check
  confirms that the installed version is not blocked.
- Optional updates open a detailed, non-modal window while normal application
  initialization continues. Mandatory updates prevent the application runtime
  from starting and offer only the official Releases page or application exit.
- The custom Libadwaita window presents the short summary immediately and keeps
  the complete per-release changelog in a native collapsed expander row.
- Added the same manual check to About, with clear results for available,
  current, unreachable, and invalid-manifest states.
- Added strict SemVer comparison, including prerelease precedence, without
  string-based version ordering.
- Added bounded downloads, strict JSON and UTC date validation, an eight-second
  network timeout, no-cache requests, and fail-open startup behavior when
  GitHub is unavailable.

## 0.1.14 — 2026-08-08

- Replaced automatic first synchronization with a protected initialization
  review. A completely new private staging folder obtains the server snapshot,
  so a stale `.sync_*.db` in the selected local folder is never reused.
- Added an explicit analysis of local-only, Nextcloud-only, identical, content
  conflict, and file-versus-folder paths before normal synchronization starts.
- Added four user-controlled conflict policies: preserve both with the newest at
  the original path, give Nextcloud priority, give the computer priority, or
  review every conflict individually. The non-preferred version is always kept
  under a clear dated name.
- Existing synchronization databases are archived outside the synchronized tree
  before a clean final baseline is created. They are never silently deleted or
  reused during initialization.
- Upgrades from schema 1, including version 0.1.13, start paused and require the
  same protected review before automatic triggers or `nextcloudcmd` are enabled.
- Added a persistent safety manifest for the last verified synchronization.
  Missing, replaced, emptied, unreadable, or abnormally reduced local folders
  block synchronization before the bidirectional engine starts.
- Added recovery from Nextcloud, explicit one-time approval for intentional
  deletions, tray and main-window warning states, desktop notifications, and
  configurable file-count and percentage thresholds.
- Kept all credential, GNOME integration, low-memory UI, translation, and Debian
  upgrade fixes from version 0.1.13.

## 0.1.13 — 2026-08-07

- Fixed the remaining GNOME biometric-login credential bug. During desktop
  autostart, GNOME Keyring could return an empty Secret Service search while
  the default Login collection was still locked, causing version 0.1.12 to
  report that no stored credential existed without displaying an unlock prompt.
- The credential flow now resolves the default password collection explicitly,
  requests its native GNOME unlock prompt when locked, confirms the collection
  was unlocked, and only then searches for the stored Nextcloud app password.
- Canceling the native prompt still preserves the dedicated **Password keyring
  locked** state and does not create repeated automatic prompts or mislabel the
  Nextcloud account as invalid.
- Added diagnostic log messages for collection unlocking and truly empty
  credential searches, plus a regression test reproducing the real startup
  sequence in which locked items are initially hidden from attribute search.

## 0.1.12 — 2026-08-07

- Fixed the remaining Debian upgrade lifecycle bug. `gapplication list-apps`
  enumerates desktop entries that advertise D-Bus activation; it does not
  report which applications are currently running, so version 0.1.11 could
  still leave the old process in memory.
- The new package now queries `org.freedesktop.DBus.NameHasOwner` on every live
  user session, invokes the application's real `quit` action, and confirms that
  the D-Bus name has been released before allowing package files to be replaced.
- A previously running session is recorded before shutdown and reopened with
  the updated application after configuration. If the application does not
  exit within the safety timeout, the upgrade stops instead of silently
  continuing over a running process.
- Replaced the inaccurate `list-apps` test double with an executable regression
  test in which `list-apps` is empty while the live D-Bus name is owned,
  matching the actual GLib behavior.

## 0.1.11 — 2026-08-07

- Fixed Debian upgrade session discovery. Maintainer scripts no longer depend
  on `SUDO_UID`, which is not reliably propagated by APT/dpkg and caused the
  running old version to remain in memory during the 0.1.10 upgrade.
- Upgrades now inspect the real per-user D-Bus sessions under `/run/user`, ask
  every running PyNextCloud Sync instance to quit normally, wait for any active
  synchronization to finish, and reopen only the sessions that were running.
- Added an executable maintainer-script regression test that reproduces an
  upgrade without `SUDO_UID` and verifies both graceful shutdown and restart.

## 0.1.10 — 2026-08-07

- Fixed startup after biometric GNOME login by searching Secret Service with
  native unlock and secret-loading flags. The GNOME Keyring prompt can now
  unlock the Login collection without exposing the desktop password to the
  application.
- A canceled unlock prompt now leaves the application in the dedicated
  **Password keyring locked** state instead of reporting that the Nextcloud
  account needs attention.
- Automatic filesystem, timer, push, resume, and network triggers are queued
  while the keyring remains locked, preventing repeated unlock prompts. The
  **Unlock Password Keyring** action retries explicitly and resumes both file
  synchronization and `notify_push` after success.
- Debian upgrades started with `sudo apt install` now request a graceful quit
  from a running instance, wait for an active synchronization to finish, and
  restart version 0.1.10 in the same desktop session. No process is force-killed.
- Added credential, locked-state, prompt-coalescing, and Debian maintainer-script
  regression tests.

## 0.1.9 — 2026-08-07

- Published the corrected website, source, issue, and changelog links in a new
  package version so systems with `0.1.8` installed apply the update normally.
- Added artifact-level validation for the canonical
  `https://github.com/ehstbr/PyNextCloud-Sync` repository and against the former
  repository URL.

## 0.1.8 — 2026-08-07

- Set the public project website to `eduhcommerce.com.br` across application,
  AppStream, Python, and Debian metadata.
- Updated source, issue, and documentation links to the canonical
  `ehstbr/PyNextCloud-Sync` repository.
- Added complete English and Brazilian Portuguese GitHub documentation with a
  screenshot gallery, compatibility statement, expanded terms, and third-party
  project/license references.
- Added a native GTK bookmark for the synchronized folder in the Files sidebar.
- Added an optional symbolic link to the synchronized folder in the XDG Desktop
  directory, with collision-safe naming and no replacement of existing files.
- Added a branded GNOME-style folder icon to the synchronized folder and its
  shortcuts through GIO metadata.
- Added independent switches for the Files bookmark, desktop shortcut, and
  special icon under Settings → General → Local Folder.
- The switches read the actual desktop state instead of duplicating it in the
  application configuration. Removing the bookmark in Files is reflected while
  Settings is open and whenever it is opened again.
- New account setup enables the three integrations. Removing the account cleans
  them up without deleting the local synchronized folder or any file inside it.

## 0.1.7 — 2026-08-07

- Replaced the parent-dependent preferences dialog with a standalone
  preferences window.
- Settings now opens directly from the tray without creating, presenting, or
  retaining the main window.
- The same settings window is reused while open and released after closing to
  preserve the lazy, low-memory UI lifecycle.

## 0.1.6 — 2026-08-07

- Fixed the tray Settings action so it maps the main window before presenting
  its adaptive preferences dialog.
- The main window is now created only when needed and releases its widgets,
  subscriptions, and child windows when closed, while synchronization and the
  tray continue running.
- Replaced unbounded `nextcloudcmd` output accumulation with incremental
  classification and a fixed 200-line diagnostic tail.
- Made log opening read only the requested tail from daily files and limited
  the live log text buffer to 2,000 lines.
- Coalesced bursts of activity updates and retained a bounded 500-line live
  history for sessions with persistent logs disabled.
- Reduced per-directory inotify memory and stopped logging every filesystem
  event at the normal information level.
- Avoided rebuilding inotify watches, timers, and push connections for
  unrelated setting changes.
- Prevented overlapping credential-preparation runs, duplicate setup startup
  synchronization, and overlapping Login Flow polling requests.
- Removed unused constants, helpers, imports, and support for the obsolete
  single-file log name. Existing files are not deleted.

## 0.1.5 — 2026-08-07

- Recent Activity rows now expand to show their complete message when clicked
  and collapse back to one ellipsized line when clicked again.
- Added a right-click context menu that copies the complete activity message.
- Bundled compiled translation catalogs with the ZIP and made locale discovery
  robust for `pt_BR`, `pt-BR`, encoding suffixes, and installed packages.
- Completed the Brazilian Portuguese catalog so application-owned status,
  setup, settings, notification, and tray text no longer falls back to English.
- Treats a terminal `Ctrl+C` as a clean interruption without printing a Python
  traceback.

## 0.1.4 — 2026-08-07

- Fixed live tray icon updates by mapping every application state to its own
  symbolic status asset instead of always returning the main application icon.
- State changes now notify tray hosts through both StatusNotifierItem signals
  and the standard D-Bus `PropertiesChanged` signal.
- Tray title, tooltip, attention state, and Pause/Resume menu action now update
  together with the icon.

## 0.1.3 — 2026-08-07

- Fixed the tray icon on GNOME AppIndicator hosts by exporting
  `IconThemePath` from the StatusNotifierItem itself.
- The indicator now publishes the application's absolute SVG path as its
  primary icon and retains ARGB pixmaps as an independent fallback.
- Aligned the StatusNotifierItem `WindowId` property with the signed integer
  type expected by current GNOME/KDE hosts.

## 0.1.2 — 2026-08-07

- Redesigned the main window as a more compact horizontal layout for smaller
  monitors, with a fixed-size status icon and responsive action buttons.
- Replaced the always-open activity list with a collapsed activity section,
  severity icons, one-line ellipsized messages, and literal text rendering.
- Fixed the StatusNotifier D-Bus menu structure and made one click open the
  menu. Added a branded pixel fallback when the tray host cannot find icons.
- Added optional daily log files, configurable 1–365 day retention, log folder
  details, and live activity when persistent logging is disabled.
- Expanded About with GitHub links, issue reporting, valid AppStream release
  notes, full MIT license, terms, credits, changelog history, and debug info.
- Fixed numeric logging arguments being converted to strings by redaction.
- Made local and remote interval controls appear only while enabled.
- Avoided duplicate presentation calls when opening the window from the tray.

## 0.1.1 — 2026-08-07

- Fixed saving, reading, and removing credentials with GNOME Keyring on
  PyGObject versions that do not expose the low-level asynchronous libsecret
  entry points.
- Keyring operations now run outside the GTK main thread, so an unlock prompt
  cannot freeze the application.
- Credential-storage failures are no longer mislabeled as an invalid Nextcloud
  Login Flow response.

## 0.1.0 — 2026-08-07

- Initial executable development release.
- Single-account setup with Nextcloud Login Flow v2 and manual sign-in.
- Secure credentials through Secret Service / GNOME Keyring.
- Bidirectional synchronization through `nextcloudcmd`.
- Recursive Linux inotify monitoring with debounce and watch-limit fallback.
- Independent local interval, notify_push, and remote safety interval triggers.
- Single coalescing synchronization queue and manual-only mode.
- GTK4/Libadwaita setup, main, settings, log, and About interfaces.
- StatusNotifierItem tray integration without a GTK3 helper process.
- Network, battery, suspend, notifications, autostart, logs, and exclusions.
- English source UI plus Brazilian Portuguese and Spanish translations.
