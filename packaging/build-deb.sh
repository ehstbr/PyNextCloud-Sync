#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$project_root/dist}"
package_name="pynextcloud-sync"
source_date_epoch="${SOURCE_DATE_EPOCH:-1786243825}"

for command_name in dpkg-deb install find sort xargs md5sum gzip sed grep du awk mktemp rm touch chmod; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required build command not found: $command_name" >&2
        exit 2
    fi
done

version="$(sed -n 's/^VERSION = "\([^"]*\)"/\1/p' "$project_root/src/pynextcloud_sync/__init__.py")"
if [[ -z "$version" ]]; then
    echo "Could not determine the application version." >&2
    exit 2
fi

for version_file in "$project_root/meson.build" "$project_root/pyproject.toml" "$project_root/data/com.eduhcommerce.PyNextCloudSync.metainfo.xml"; do
    if ! grep -Fq "$version" "$version_file"; then
        echo "Version $version is not present in ${version_file#$project_root/}." >&2
        exit 2
    fi
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/pynextcloud-sync-deb.XXXXXX")"
cleanup() {
    case "$work_dir" in
        /tmp/pynextcloud-sync-deb.*|"${TMPDIR:-/tmp}"/pynextcloud-sync-deb.*)
            rm -rf -- "$work_dir"
            ;;
    esac
}
trap cleanup EXIT

package_root="$work_dir/${package_name}_${version}_all"
python_dir="$package_root/usr/lib/python3/dist-packages"
doc_dir="$package_root/usr/share/doc/$package_name"

install -d -m 0755 \
    "$package_root/DEBIAN" \
    "$package_root/usr/bin" \
    "$python_dir" \
    "$package_root/usr/share/applications" \
    "$package_root/usr/share/metainfo" \
    "$package_root/usr/share/icons/hicolor/scalable/apps" \
    "$package_root/usr/share/icons/hicolor/scalable/places" \
    "$package_root/usr/share/icons/hicolor/symbolic/apps" \
    "$package_root/usr/share/icons/hicolor/symbolic/status" \
    "$doc_dir"

while IFS= read -r -d '' source_file; do
    relative_path="${source_file#$project_root/src/}"
    install -D -m 0644 "$source_file" "$python_dir/$relative_path"
done < <(find "$project_root/src/pynextcloud_sync" -type f -name '*.py' -print0 | sort -z)

install -m 0755 "$project_root/packaging/debian/pynextcloud-sync" "$package_root/usr/bin/pynextcloud-sync"
install -m 0644 "$project_root/data/com.eduhcommerce.PyNextCloudSync.desktop" "$package_root/usr/share/applications/"
install -m 0644 "$project_root/data/com.eduhcommerce.PyNextCloudSync.metainfo.xml" "$package_root/usr/share/metainfo/"
install -m 0644 "$project_root/data/icons/com.eduhcommerce.PyNextCloudSync.svg" "$package_root/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "$project_root/data/icons/com.eduhcommerce.PyNextCloudSync-symbolic.svg" "$package_root/usr/share/icons/hicolor/symbolic/apps/"
install -m 0644 "$project_root/data/icons/com.eduhcommerce.PyNextCloudSync-folder.svg" "$package_root/usr/share/icons/hicolor/scalable/places/"
install -m 0644 "$project_root/data/icons/status/"*.svg "$package_root/usr/share/icons/hicolor/symbolic/status/"

for language in pt_BR es; do
    install -D -m 0644 \
        "$project_root/locale/$language/LC_MESSAGES/pynextcloud-sync.mo" \
        "$package_root/usr/share/locale/$language/LC_MESSAGES/pynextcloud-sync.mo"
done

install -m 0644 \
    "$project_root/README.md" \
    "$project_root/README.pt-BR.md" \
    "$project_root/LICENSE" \
    "$project_root/TERMS.md" \
    "$project_root/TERMS.pt-BR.md" \
    "$project_root/THIRD-PARTY.md" \
    "$project_root/THIRD-PARTY.pt-BR.md" \
    "$project_root/version.json" \
    "$doc_dir/"
install -m 0644 "$project_root/packaging/debian/copyright" "$doc_dir/copyright"
gzip -9nc "$project_root/CHANGELOG.md" > "$doc_dir/changelog.gz"
gzip -9nc "$project_root/packaging/debian/changelog" > "$doc_dir/changelog.Debian.gz"

install -m 0755 "$project_root/packaging/debian/preinst" "$package_root/DEBIAN/preinst"
install -m 0755 "$project_root/packaging/debian/postinst" "$package_root/DEBIAN/postinst"
install -m 0755 "$project_root/packaging/debian/postrm" "$package_root/DEBIAN/postrm"

installed_size="$(du -sk "$package_root/usr" | awk '{print $1}')"
sed \
    -e "s/@VERSION@/$version/g" \
    -e "s/@INSTALLED_SIZE@/$installed_size/g" \
    "$project_root/packaging/debian/binary-control.in" > "$package_root/DEBIAN/control"
chmod 0644 "$package_root/DEBIAN/control"

(
    cd "$package_root"
    find usr -type f -print0 | sort -z | xargs -0 md5sum
) > "$package_root/DEBIAN/md5sums"
chmod 0644 "$package_root/DEBIAN/md5sums"

find "$package_root" -exec touch -h -d "@$source_date_epoch" {} +
install -d -m 0755 "$output_dir"
output_file="$output_dir/${package_name}_${version}_all.deb"
SOURCE_DATE_EPOCH="$source_date_epoch" dpkg-deb \
    --root-owner-group \
    --uniform-compression \
    -Zxz -z9 \
    --build "$package_root" "$output_file"

echo "$output_file"
sha256sum "$output_file"
