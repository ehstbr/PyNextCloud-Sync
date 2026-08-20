<div align="center">
  <img src="data/icons/com.eduhcommerce.PyNextCloudSync.svg" width="112" alt="PyNextCloud Sync icon">
  <h1>PyNextCloud Sync</h1>
  <p><strong>Your files, local. Your Nextcloud, in sync.</strong></p>
  <p>A lightweight, GNOME-native desktop companion for keeping one complete physical copy of a Nextcloud account on Linux.</p>
  <p>
    <a href="README.pt-BR.md">Português (Brasil)</a>
    ·
    <a href="https://eduhcommerce.com.br">Website</a>
    ·
    <a href="https://github.com/ehstbr/PyNextCloud-Sync/releases">Releases</a>
    ·
    <a href="https://github.com/ehstbr/PyNextCloud-Sync/issues">Report an issue</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/version-0.1.32-6557e8?style=flat-square" alt="Version 0.1.32">
    <img src="https://img.shields.io/badge/platform-Linux-f0c674?style=flat-square&logo=linux&logoColor=111" alt="Linux">
    <img src="https://img.shields.io/badge/desktop-GNOME-4a86cf?style=flat-square&logo=gnome&logoColor=white" alt="GNOME">
    <img src="https://img.shields.io/badge/GTK-4-4a86cf?style=flat-square&logo=gtk&logoColor=white" alt="GTK 4">
    <img src="https://img.shields.io/badge/license-GPLv3%2B-2da44e?style=flat-square" alt="GNU GPLv3 or later">
  </p>
</div>

<p align="center">
  <img src="docs/screenshots/main-window.png" width="820" alt="PyNextCloud Sync main window while synchronizing">
</p>

## A small app with one clear job

PyNextCloud Sync keeps **one Nextcloud account** mirrored to **one local folder**. It deliberately avoids selective-sync rules, virtual files, multiple account trees, dashboards, and unrelated cloud features.

The actual bidirectional reconciliation is performed by the official [`nextcloudcmd`](https://github.com/nextcloud/desktop) engine. PyNextCloud Sync adds the desktop experience around it: secure login, automatic triggers, a compact status window, GNOME integration, logs, and a tray menu.

### Highlights

- **Complete physical mirror:** every eligible file in the account is kept locally.
- **Official synchronization engine:** no custom WebDAV reconciliation algorithm.
- **GNOME-native interface:** GTK 4 and Libadwaita, with a compact and familiar layout.
- **Secure sign-in:** Nextcloud Login Flow v2 or manual credentials, stored through Secret Service / GNOME Keyring.
- **Account-aware authorization:** stable per-computer authorization names, in-place reconnection, and a dedicated account information page.
- **Visible storage usage:** the home page shows bounded quota occupancy or an unlimited server-storage state.
- **Fast local detection:** recursive Linux `inotify` monitoring with event coalescing.
- **Remote change awareness:** optional `notify_push`, backed by a configurable safety interval.
- **Low-noise background operation:** one coalescing queue and at most one `nextcloudcmd` process.
- **Protected initialization:** before bidirectional mode, a fresh temporary folder obtains the server tree and the user reviews how both sides will be merged.
- **Abnormal-deletion guard:** a missing, replaced, empty, unreadable, or sharply reduced local tree blocks the engine before Nextcloud can be changed.
- **Useful desktop integration:** Files sidebar bookmark, Desktop shortcut, custom folder icon, autostart, notifications, and tray controls.
- **Private by design:** no telemetry, analytics, advertisements, or remote crash reporting.
- **Multilingual:** English source interface with Brazilian Portuguese and Spanish translations.

## Screenshots

<table>
  <tr>
    <td width="50%" align="center"><strong>GNOME-oriented settings</strong><br><img src="docs/screenshots/settings-general.png" alt="General settings"></td>
    <td width="50%" align="center"><strong>Independent sync triggers</strong><br><img src="docs/screenshots/settings-sync.png" alt="Synchronization settings"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><strong>Network controls</strong><br><img src="docs/screenshots/settings-network.png" alt="Network settings"></td>
    <td width="50%" align="center"><strong>Local logs and diagnostics</strong><br><img src="docs/screenshots/settings-advanced.png" alt="Advanced settings"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><strong>Optional update</strong><br><img src="docs/screenshots/update-optional.png" alt="Optional update available"></td>
    <td width="50%" align="center"><strong>Mandatory update</strong><br><img src="docs/screenshots/update-mandatory.png" alt="Mandatory update required"></td>
  </tr>
</table>

<p align="center">
  <strong>Everything important is also available from the tray</strong><br><br>
  <img src="docs/screenshots/tray-menu.png" width="368" alt="PyNextCloud Sync tray menu">
</p>

<details>
<summary><strong>View the first-run setup</strong></summary>
<br>
<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/welcome.png" alt="Welcome screen"></td>
    <td width="50%"><img src="docs/screenshots/connect.png" alt="Nextcloud server address"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/sign-in.png" alt="Sign-in choices"></td>
    <td width="50%"><img src="docs/screenshots/browser-sign-in.png" alt="Waiting for browser authorization"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/local-folder.png" alt="Local folder selection"></td>
    <td width="50%"><img src="docs/screenshots/review.png" alt="Configuration review"></td>
  </tr>
</table>
</details>

## How synchronization works

Every trigger asks the same scheduler for a bidirectional reconciliation. Requests that arrive together are coalesced, and the app never intentionally starts two `nextcloudcmd` processes for the same account.

```mermaid
flowchart LR
    A["Local changes<br>inotify / interval"] --> Q["Single<br>sync queue"]
    B["Remote hints<br>notify_push / interval"] --> Q
    C["Manual sync<br>network / resume"] --> Q
    Q --> N["nextcloudcmd"]
    N <--> F["Local mirror"]
    N <--> S["Nextcloud server"]
```

`notify_push` sends only a hint that something may have changed. File discovery, transfer, conflict handling, and deletion propagation remain the responsibility of `nextcloudcmd`.

> [!IMPORTANT]
> Synchronization is bidirectional. Local and remote changes—including deletions—can be propagated to the other side. Keep an independent backup of important data and do not run another synchronization engine against the same local folder.

## Installation

### Debian package — recommended

Download the `.deb` from the [latest release](https://github.com/ehstbr/PyNextCloud-Sync/releases/latest), then install it with APT so the required system packages are resolved automatically:

```bash
cd ~/Downloads
sudo apt update
sudo apt install ./pynextcloud-sync_0.1.32_all.deb
```

During an interactive upgrade started with `sudo apt install`, the package asks a running PyNextCloud Sync instance to quit normally, waits for any current synchronization to finish, and restarts the updated application in the same desktop session. It never force-kills the synchronization process. Non-interactive upgrades or installations without an identifiable desktop session leave process control to the user or system administrator.

The package depends on `nextcloud-desktop-cmd`, Python 3, GTK 4, Libadwaita, PyGObject, libsoup, libsecret, GdkPixbuf, and GNOME Keyring. On GNOME, tray icons normally require an AppIndicator/StatusNotifier extension; synchronization continues even when no tray host is available.

### Source ZIP

Install the runtime dependencies first:

```bash
sudo apt update
sudo apt install \
  python3 python3-gi \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 \
  gir1.2-soup-3.0 gir1.2-secret-1 \
  nextcloud-desktop-cmd
```

Then extract and run:

```bash
unzip PyNextCloud-Sync-0.1.32.zip
cd PyNextCloud-Sync-0.1.32
./run.sh
```

`run.sh` uses the distribution Python and GI packages. It does not create a virtual environment or download packages from the internet.

## First setup

1. Enter the base URL normally used to open your Nextcloud server.
2. Prefer **Sign in with browser** for Login Flow v2 and two-factor authentication support. Manual username plus password/app-password is also available.
3. Choose the local mirror folder. The default is `$HOME/NextCloud`.
4. Review the configuration and start the protected analysis.
5. Check computer-only, Nextcloud-only, identical, conflicting, and old synchronization-state paths.
6. Merge while preserving both versions, prioritize Nextcloud, prioritize the computer, or decide each conflict individually.

The analysis uses a completely new private folder to obtain a protected server snapshot. Any `.sync_*.db` found in the selected local folder is identified and archived outside the synchronized tree; it is never reused silently. Bidirectional mode, `inotify`, timers, and `notify_push` are enabled only after the reviewed result is applied, verified, and saved as a safety baseline.

New account setup then enables local filesystem monitoring, a 10-minute remote safety interval, compatible server push, disposable-file exclusions, and autostart. It also adds the synchronized folder to the Files sidebar, creates a safe symbolic link on the XDG Desktop, and applies the PyNextCloud Sync folder icon. These integrations can be changed independently in **Settings → General → Local Folder**.

Installations upgraded from `0.1.13` also start paused and go through this review once. This is intentional: the new release does not treat an older state without its own safety manifest as trusted.

## Account and authorization management

Browser sign-in identifies new Nextcloud authorizations as `PyNextCloud-Sync (hostname)`, making separate computers recognizable without tying the authorization name to the installed application version.

**Settings → Account** groups the configured identity, local folder, recorded authorization name, display name, email, storage quota, and basic server status. If an app password is revoked, **Reconnect Account** renews only that authorization. It does not reset the local folder, synchronization preferences, or the existing safety baseline. The renewed credential is verified before a normal protected synchronization resumes.

The home page shows the last saved storage use with a proportional progress bar and its percentage centered inside when the account has a defined quota. Accounts without a defined quota use a static empty bar with an infinity symbol and report the amount used, making clear that the practical limit is the storage available on the server. Opening Home or Settings does not trigger another request: saved details appear immediately. Account identity and basic server information are refreshed once when the application process starts, while storage usage is refreshed again after every successful synchronization. **Settings → Account → Refresh Account Information** remains available for an explicit manual update.

## Continuous deletion protection

After every successful synchronization, PyNextCloud Sync records a local manifest of the verified tree. Before another bidirectional run, it verifies the folder identity and its basic contents.

Synchronization is blocked when:

- the local folder is missing, is no longer a directory, or cannot be read;
- the configured folder appears to have been replaced or remounted;
- a previously populated folder becomes empty;
- the `nextcloudcmd` state database disappears unexpectedly;
- at least 10 files or 20% of the previous baseline disappear, according to configurable limits.

The safety review lets the user restore from Nextcloud, remain paused, or explicitly approve those deletions for one run. An urgent GNOME notification calls attention to the block and its **Review Now** action opens the confirmation directly. Limits are available under **Settings → Advanced → Deletion Safety Guard**. Empty, missing, replaced, and unreadable folders always require review regardless of those limits.

This guard deliberately covers local changes before they can be propagated to Nextcloud. Deletions originating on the server or another synchronized computer are still applied locally by `nextcloudcmd` without this confirmation.

If Files removes the sidebar bookmark, the application respects that choice and reflects the real state instead of recreating it.

## Update checks

At every application startup, PyNextCloud Sync reads `version.json` from the
root of the GitHub repository before enabling the synchronization runtime. An
unreachable GitHub service, HTTP failure, or invalid manifest is logged and
does not prevent normal startup.

| Field | Purpose |
| --- | --- |
| `schema_version` | Version of the manifest contract |
| `version` | Latest release using SemVer |
| `mandatory` | Prevents older versions from running when `true` |
| `released_at` | ISO 8601 release date and time in UTC |
| `summary` | Short plain-text release summary |
| `changelog` | Complete ordered list of plain-text changes |

Optional updates use a non-modal Libadwaita window, so normal initialization
continues. Mandatory updates keep the runtime, filesystem monitoring, timers,
and push connection disabled and offer only the official Releases page or
application exit. The same validation can be started manually from **About →
Check for Updates**. The detailed changelog remains collapsed until requested.

## Configuration model

| Area | What it controls |
| --- | --- |
| General | Autostart, battery behavior, local folder, Files bookmark, Desktop shortcut, and branded folder icon |
| Synchronization | `inotify`, local interval, `notify_push`, remote safety interval, and disposable-file exclusions |
| Network | Account removal, optional HTTP proxy, and explicit opt-in for invalid/self-signed certificates |
| Advanced | Daily logs, retention, detailed output, deletion-guard limits, and runtime diagnostics |

All four automatic triggers can be combined or disabled. With local monitoring, local interval, server push, and remote interval all disabled, the application operates in manual-only mode.

## Compatibility

Currently tested with [**Nextcloud Hub 26 Spring**](https://nextcloud.com/) **(34.0.1)** deployed with **Nextcloud AIO**.

Compatibility with other installations may depend on the installed `nextcloudcmd`, server configuration, reverse proxy, authentication method, and optional apps. Future versions of Nextcloud are not guaranteed to remain compatible.

## Exclusions

The default rules cover conservative disposable files such as `.DS_Store`, `Thumbs.db`, office lock files, Vim swap files, backup suffixes, and the `nextcloudcmd` journal noise file. Hidden user files remain eligible for synchronization because the client is always invoked with hidden-file support.

Patterns containing `/`, `\`, or `..` are rejected. Version 1 does not support folder, path, or remote-subtree exclusions.

## Files, credentials, and privacy

- Configuration: `$XDG_CONFIG_HOME/pynextcloud-sync/settings.json`
- Generated exclusions: `$XDG_CONFIG_HOME/pynextcloud-sync/excludes.lst`
- Daily logs: `$XDG_STATE_HOME/pynextcloud-sync/pynextcloud-sync-YYYY-MM-DD.log`
- Safety manifest: `$XDG_STATE_HOME/pynextcloud-sync/safety-manifest.json`
- Archived old state databases: `$XDG_STATE_HOME/pynextcloud-sync/safety-archives/`
- Account secret: GNOME Keyring or another compatible Secret Service provider

Logs remain local, use one file per day, and are retained for 30 days by default. Sensitive values are redacted from application-owned log messages. If biometric desktop login leaves the Login keyring locked, GNOME shows its native unlock prompt before synchronization. The desktop password is handled only by GNOME; PyNextCloud Sync does not receive or store it. Canceling the prompt leaves the app waiting for an explicit **Unlock Password Keyring** request instead of repeatedly prompting or reporting invalid Nextcloud credentials.

## Development and tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

The pure-Python suite includes a fake `nextcloudcmd` for success, failure, authentication failure, output, and slow-run scenarios. Real account, GNOME tray host, UPower, suspend/resume, and long-running memory tests still require an actual desktop session.

Contributions are welcome when they preserve the project's narrow scope, low idle resource use, secure credential handling, and GNOME-oriented design. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

- [Changelog](CHANGELOG.md)
- [Terms of Use](TERMS.md)
- [GNU General Public License v3 or later](LICENSE)
- [Third-party projects and licenses](THIRD-PARTY.md)
- [Contributing](CONTRIBUTING.md)

## Project status

Version `0.1.32` is a development release intended for evaluation. Test it with non-critical data before relying on it for regular synchronization, and always keep independent backups of important files.

---

<p align="center"><sub>
Nextcloud® is a registered trademark of Nextcloud GmbH. PyNextCloud Sync is an independent, unofficial project and is not affiliated with, sponsored by, endorsed by, or otherwise connected to Nextcloud GmbH. Use is subject to the <a href="TERMS.md">Terms of Use</a> and the GNU General Public License version 3 or later.
</sub></p>
