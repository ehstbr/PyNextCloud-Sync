#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"

if ! "$python_bin" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("GdkPixbuf", "2.0"); gi.require_version("Soup", "3.0"); gi.require_version("Secret", "1")' 2>/dev/null; then
    echo "PyNextCloud Sync requires the GNOME Python bindings."
    echo
    echo "On Ubuntu/Debian, install:"
    echo "  sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 gir1.2-soup-3.0 gir1.2-secret-1 nextcloud-desktop-cmd"
    exit 2
fi

locale_dir="$project_root/locale"
if command -v msgfmt >/dev/null 2>&1; then
    for language in pt_BR es; do
        source_file="$project_root/po/$language.po"
        target_dir="$locale_dir/$language/LC_MESSAGES"
        target_file="$target_dir/pynextcloud-sync.mo"
        if [[ -f "$source_file" && ( ! -f "$target_file" || "$source_file" -nt "$target_file" ) ]]; then
            mkdir -p "$target_dir"
            msgfmt --check --output-file="$target_file" "$source_file"
        fi
    done
fi

export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
export PYNEXTCLOUD_LAUNCHER="$project_root/run.sh"
export PYNEXTCLOUD_LOCALE_DIR="$locale_dir"
exec "$python_bin" -m pynextcloud_sync "$@"
