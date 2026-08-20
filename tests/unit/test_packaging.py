from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class PackagingTests(unittest.TestCase):
    def test_release_version_is_consistent_across_package_metadata(self) -> None:
        expected = "0.1.32"
        for relative_path in (
            "src/pynextcloud_sync/__init__.py",
            "pyproject.toml",
            "meson.build",
            "data/com.eduhcommerce.PyNextCloudSync.metainfo.xml",
            "packaging/debian/changelog",
            "CHANGELOG.md",
            "README.md",
            "README.pt-BR.md",
            "version.json",
        ):
            contents = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(expected, contents, relative_path)

    def test_repository_update_manifest_matches_the_release(self) -> None:
        payload = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["version"], "0.1.32")
        self.assertIs(type(payload["mandatory"]), bool)
        self.assertTrue(payload["summary"].strip())
        self.assertGreater(len(payload["changelog"]), 0)
        self.assertTrue(all(item.strip() for item in payload["changelog"]))
        self.assertRegex(payload["released_at"], r"^\d{4}-\d{2}-\d{2}T.*Z$")

    def test_debian_package_includes_the_published_manifest(self) -> None:
        build = (ROOT / "packaging/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn('"$project_root/version.json"', build)

    def test_maintainer_scripts_have_valid_shell_syntax(self) -> None:
        for name in ("preinst", "postinst", "postrm"):
            path = ROOT / "packaging" / "debian" / name
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_upgrade_requests_graceful_quit_and_restarts_in_user_session(self) -> None:
        preinst = (ROOT / "packaging/debian/preinst").read_text(encoding="utf-8")
        postinst = (ROOT / "packaging/debian/postinst").read_text(encoding="utf-8")
        build = (ROOT / "packaging/build-deb.sh").read_text(encoding="utf-8")
        source_build = (ROOT / "packaging/build-source-zip.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("SUDO_UID", preinst)
        self.assertNotIn("SUDO_UID", postinst)
        self.assertIn('"$runtime_root"/[0-9]*/bus', preinst)
        self.assertIn("org.freedesktop.DBus.NameHasOwner", preinst)
        self.assertNotIn("gapplication list-apps", preinst)
        self.assertIn('gapplication action "$app_id" quit', preinst)
        self.assertIn('while app_is_running "$session_uid"', preinst)
        self.assertNotIn("pkill", preinst)
        self.assertNotIn("kill -", preinst)
        self.assertIn('done < "$restart_file"', postinst)
        self.assertIn("systemd-run --user", postinst)
        self.assertIn("pynextcloud-sync --background", postinst)
        self.assertIn('packaging/debian/preinst', build)
        self.assertIn('output_dir="$(cd "$output_dir" && pwd)"', source_build)

    def test_upgrade_lifecycle_works_without_sudo_uid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            runtime_root = temporary / "run" / "user"
            state_dir = temporary / "run" / "pynextcloud-sync-upgrade"
            session_dir = runtime_root / "1000"
            fake_bin = temporary / "bin"
            session_dir.mkdir(parents=True)
            fake_bin.mkdir()

            (session_dir / "bus").touch()

            app_state = temporary / "app-running"
            app_state.touch()
            restart_log = temporary / "restart.log"

            self._write_executable(
                fake_bin / "getent",
                """#!/bin/sh
if [ "$1" = "passwd" ]; then
    printf 'desktop:x:%s:%s::/tmp:/bin/sh\\n' "$2" "$2"
fi
""",
            )
            self._write_executable(
                fake_bin / "runuser",
                """#!/bin/sh
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ "$#" -gt 0 ] && shift
exec "$@"
""",
            )
            self._write_executable(
                fake_bin / "gapplication",
                """#!/bin/sh
case "$1" in
    list-apps)
        # This deliberately returns no applications. The real command lists
        # D-Bus-activatable desktop entries, not running processes.
        exit 0
        ;;
    action)
        mv "$PYNEXTCLOUD_TEST_APP_STATE" "$PYNEXTCLOUD_TEST_APP_STATE.stopped"
        ;;
    *)
        exit 2
        ;;
esac
""",
            )
            self._write_executable(
                fake_bin / "gdbus",
                """#!/bin/sh
if [ -f "$PYNEXTCLOUD_TEST_APP_STATE" ]; then
    printf '%s\\n' '(true,)'
else
    printf '%s\\n' '(false,)'
fi
""",
            )
            self._write_executable(
                fake_bin / "systemd-run",
                """#!/bin/sh
printf '%s\\n' "$*" > "$PYNEXTCLOUD_TEST_RESTART_LOG"
""",
            )
            for command_name in ("update-desktop-database", "gtk-update-icon-cache"):
                self._write_executable(fake_bin / command_name, "#!/bin/sh\nexit 0\n")

            preinst = self._patched_maintainer_script(
                "preinst", temporary, runtime_root, state_dir
            )
            postinst = self._patched_maintainer_script(
                "postinst", temporary, runtime_root, state_dir
            )
            environment = os.environ.copy()
            environment.pop("SUDO_UID", None)
            environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
            environment["PYNEXTCLOUD_TEST_APP_STATE"] = str(app_state)
            environment["PYNEXTCLOUD_TEST_RESTART_LOG"] = str(restart_log)

            stopped = subprocess.run(
                ["/bin/sh", str(preinst), "upgrade", "0.1.16", "0.1.17"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertIn("requesting a safe shutdown", stopped.stdout)
            self.assertFalse(app_state.exists())
            self.assertEqual((state_dir / "restart-uids").read_text(), "1000\n")

            restarted = subprocess.run(
                ["/bin/sh", str(postinst), "configure", "0.1.12"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertIn("Restarting PyNextCloud Sync", restarted.stdout)
            restart_arguments = restart_log.read_text(encoding="utf-8")
            self.assertIn("/usr/bin/pynextcloud-sync --background", restart_arguments)
            self.assertEqual((state_dir / "restart-uids").read_text(), "")

    @staticmethod
    def _write_executable(path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)

    @staticmethod
    def _patched_maintainer_script(
        name: str, temporary: Path, runtime_root: Path, state_dir: Path
    ) -> Path:
        contents = (ROOT / "packaging" / "debian" / name).read_text(
            encoding="utf-8"
        )
        contents = contents.replace('/run/user', str(runtime_root))
        contents = contents.replace('/run/pynextcloud-sync-upgrade', str(state_dir))
        # This execution environment blocks AF_UNIX socket creation. Production
        # still requires a socket; the test substitutes an ordinary fixture file.
        contents = contents.replace('-S "$session_bus"', '-e "$session_bus"')
        path = temporary / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)
        return path


if __name__ == "__main__":
    unittest.main()
