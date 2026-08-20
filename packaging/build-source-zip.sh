#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$project_root/dist}"
source_date_epoch="${SOURCE_DATE_EPOCH:-1786243825}"

for command_name in find grep mkdir mktemp rm sed sort tar touch zip; do
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

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/pynextcloud-sync-source.XXXXXX")"
cleanup() {
    case "$work_dir" in
        /tmp/pynextcloud-sync-source.*|"${TMPDIR:-/tmp}"/pynextcloud-sync-source.*)
            rm -rf -- "$work_dir"
            ;;
    esac
}
trap cleanup EXIT

archive_root="PyNextCloud-Sync-$version"
staging_dir="$work_dir/$archive_root"
mkdir -p "$staging_dir"

tar \
    --exclude='./.git' \
    --exclude='./.pytest_cache' \
    --exclude='./.mypy_cache' \
    --exclude='./.coverage' \
    --exclude='./build' \
    --exclude='./dist' \
    --exclude='./htmlcov' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.egg-info' \
    --exclude='*.deb' \
    --exclude='*.zip' \
    -C "$project_root" -cf - . | tar -C "$staging_dir" -xf -

find "$staging_dir" -exec touch -h -d "@$source_date_epoch" {} +

output_file="$output_dir/$archive_root.zip"
(
    cd "$work_dir"
    find "$archive_root" -print | LC_ALL=C sort | zip -X -9 -q "$output_file" -@
)

echo "$output_file"
sha256sum "$output_file"
