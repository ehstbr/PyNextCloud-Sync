from __future__ import annotations

import sys


def main() -> int:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("Soup", "3.0")
        gi.require_version("Secret", "1")
    except (ImportError, ValueError) as exc:
        print("PyNextCloud Sync cannot start because GNOME Python bindings are missing.", file=sys.stderr)
        print("Install the packages listed in README.md, then run ./run.sh again.", file=sys.stderr)
        print(f"Technical detail: {exc}", file=sys.stderr)
        return 2

    from .application import PyNextCloudApplication

    background = "--background" in sys.argv
    argv = [arg for arg in sys.argv if arg != "--background"]
    application = PyNextCloudApplication(background=background)
    try:
        return application.run(argv)
    except KeyboardInterrupt:
        application.quit()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
