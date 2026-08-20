# Contributing

PyNextCloud Sync is intentionally narrow: one account, one complete local mirror, and the official `nextcloudcmd` engine. Changes should preserve low idle CPU/RAM use and GNOME-native design.

Before submitting a change:

1. Run `python3 -m unittest discover -s tests -v`.
2. Run `python3 -m compileall -q src`.
3. Never put credentials in command arguments, configuration, tests, or logs.
4. Keep all user-visible source strings in English and wrap them for gettext.
5. Test synchronization behavior with the included fake `nextcloudcmd` before using a real account.

