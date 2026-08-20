# Third-party projects and licenses

PyNextCloud Sync is original software distributed under the [GNU General Public License version 3 or later](LICENSE). It relies on system packages, protocols, and independently maintained projects listed below.

The source ZIP does **not** bundle the source code or binaries of these runtime dependencies. The Debian package declares them as dependencies or recommendations, and the operating system package manager installs them separately. Each external component remains governed by its own upstream license; nothing in this repository relicenses it.

License identifiers below summarize the principal upstream license. Consult the linked project and the copyright files shipped by your Linux distribution for the complete, version-specific terms.

## Core runtime

| Project | How PyNextCloud Sync uses it | Upstream license |
| --- | --- | --- |
| [Nextcloud Desktop Client / `nextcloudcmd`](https://github.com/nextcloud/desktop) | Performs file discovery, bidirectional reconciliation, transfers, conflicts, and deletion propagation | GPL-2.0-or-later |
| [Python](https://www.python.org/) | Application runtime | Python Software Foundation License |
| [PyGObject](https://github.com/GNOME/pygobject) | Python bindings for GObject Introspection libraries | LGPL-2.1-or-later |
| [GTK 4](https://github.com/GNOME/gtk) | Graphical user interface toolkit | LGPL-2.1-or-later |
| [Libadwaita](https://github.com/GNOME/libadwaita) | GNOME application patterns and adaptive widgets | LGPL-2.1-or-later |
| [GLib / GObject / GIO](https://github.com/GNOME/glib) | Main loop, D-Bus, file monitoring, networking integration, settings helpers, and desktop services | LGPL-2.1-or-later |
| [libsoup](https://github.com/GNOME/libsoup) | HTTPS requests and WebSocket connection for Nextcloud APIs and push hints | LGPL-2.1-or-later |
| [libsecret](https://github.com/GNOME/libsecret) | Secret Service access for account credentials | LGPL-2.1-or-later |
| [GdkPixbuf](https://github.com/GNOME/gdk-pixbuf) | Application and tray image handling | LGPL-2.1-or-later |
| [GNOME Keyring](https://github.com/GNOME/gnome-keyring) | Recommended Secret Service provider on GNOME | GPL-2.0 and LGPL-2.1 components; see upstream files |

## Optional integrations

| Project | Relationship | Upstream license |
| --- | --- | --- |
| [Nextcloud Client Push (`notify_push`)](https://github.com/nextcloud/notify_push) | Optional server-side app used only to receive best-effort remote change hints; it is not bundled or installed by PyNextCloud Sync | AGPL-3.0 |
| [AppIndicator/KStatusNotifierItem GNOME Shell extension](https://github.com/ubuntu/gnome-shell-extension-appindicator) | Optional tray host recommended on GNOME; it is not bundled | GPL-2.0 |

PyNextCloud Sync implements the freedesktop StatusNotifierItem and D-Bus menu interfaces directly through GIO. It does not include or link against `libappindicator`.

## Build and translation tools

The project metadata and release workflow also support [Meson](https://github.com/mesonbuild/meson), [setuptools](https://github.com/pypa/setuptools), [GNU gettext](https://www.gnu.org/software/gettext/), and Debian packaging tools. These tools run during development or packaging and are not embedded into the application source.

## Trademarks and independence

Nextcloud® is a registered trademark of Nextcloud GmbH. GNOME and other names may be trademarks of their respective owners.

PyNextCloud Sync is independent and unofficial. Listing a project here is an attribution and compatibility notice, not a claim of affiliation, sponsorship, certification, or endorsement.
