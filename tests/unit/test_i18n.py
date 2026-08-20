from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


class I18nTests(unittest.TestCase):
    def test_bundled_pt_br_catalog_loads_with_ubuntu_locale(self) -> None:
        catalog = (
            PROJECT_ROOT
            / "locale"
            / "pt_BR"
            / "LC_MESSAGES"
            / "pynextcloud-sync.mo"
        )
        self.assertTrue(catalog.is_file(), catalog)
        environment = os.environ.copy()
        environment.update(
            {
                "LANG": "pt_BR.UTF-8",
                "LC_ALL": "",
                "LC_MESSAGES": "",
                "LANGUAGE": "",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; print(_('Recent Activity'))",
            ],
            env=environment,
            text=True,
        ).strip()
        self.assertEqual(translated, "Atividade recente")

    def test_hyphenated_language_name_is_normalized(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt-BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; print(_('Sync Now'))",
            ],
            env=environment,
            text=True,
        ).strip()
        self.assertEqual(translated, "Sincronizar agora")

    def test_desktop_integration_labels_are_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('Show in Files sidebar')); "
                "print(_('Show on Desktop')); "
                "print(_('Use special folder icon'))",
            ],
            env=environment,
            text=True,
        ).splitlines()
        self.assertEqual(
            translated,
            [
                "Mostrar na lateral do Arquivos",
                "Mostrar na Área de Trabalho",
                "Usar ícone especial na pasta",
            ],
        )

    def test_biometric_keyring_release_note_is_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('Added the native GNOME Keyring unlock prompt required after biometric desktop login.'))",
            ],
            env=environment,
            text=True,
        ).strip()
        self.assertIn("login biométrico", translated)

    def test_biometric_collection_fix_release_note_is_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('Version 0.1.14')); "
                "print(_('The default GNOME password collection is now unlocked before searching for the Nextcloud credential after biometric login.'))",
            ],
            env=environment,
            text=True,
        ).splitlines()
        self.assertEqual(translated[0], "Versão 0.1.14")
        self.assertIn("coleção de senhas padrão", translated[1])

    def test_update_window_and_manual_check_are_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('Check for Updates')); "
                "print(_('Update Available')); "
                "print(_('Required Update')); "
                "print(_('Full Changelog')); "
                "print(_('Download New Version')); "
                "print(_('Mandatory update available'))",
            ],
            env=environment,
            text=True,
        ).splitlines()
        self.assertEqual(
            translated,
            [
                "Verificar atualização",
                "Atualização disponível",
                "Atualização obrigatória",
                "Histórico completo de alterações",
                "Baixar nova versão",
                "Atualização obrigatória disponível",
            ],
        )

    def test_account_management_labels_are_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('View Account')); "
                "print(_('Authorization name in Nextcloud')); "
                "print(_('Reconnect the Nextcloud account to resume synchronization')); "
                "print(_('Storage usage')); "
                "print(_('Available after the first successful synchronization')); "
                "print(_('Not obtained yet')); "
                "print(_('{used} used · Limited only by available server storage').format(used='10 GB'))",
            ],
            env=environment,
            text=True,
        ).splitlines()
        self.assertEqual(
            translated,
            [
                "Ver conta",
                "Nome da autorização no Nextcloud",
                "Reconecte a conta do Nextcloud para retomar a sincronização",
                "Uso do armazenamento",
                "Disponível após a primeira sincronização bem-sucedida",
                "Ainda não obtido",
                "10 GB usados · Limitado apenas pelo espaço disponível no servidor",
            ],
        )

    def test_urgent_safety_notification_is_translated(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "LANGUAGE": "pt_BR",
                "PYNEXTCLOUD_LOCALE_DIR": str(PROJECT_ROOT / "locale"),
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
            }
        )
        translated = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from pynextcloud_sync.util.i18n import _; "
                "print(_('Synchronization paused for safety')); "
                "print(_('Review Now')); "
                "print(_('Local files are missing ({count}). Review the change before they can be deleted from Nextcloud.').format(count=12))",
            ],
            env=environment,
            text=True,
        ).splitlines()
        self.assertEqual(
            translated,
            [
                "Sincronização pausada por segurança",
                "Revisar agora",
                "Há arquivos locais ausentes (12). Revise a alteração antes de permitir que sejam excluídos do Nextcloud.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
