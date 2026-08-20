from __future__ import annotations

import gettext
import locale
import os
from pathlib import Path

from .paths import project_root


DOMAIN = "pynextcloud-sync"


def _locale_dirs() -> tuple[Path, ...]:
    override = os.environ.get("PYNEXTCLOUD_LOCALE_DIR")
    candidates = [
        Path(override) if override else None,
        project_root() / "locale",
        project_root() / "build" / "locale",
        Path("/usr/share/locale"),
    ]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate is not None and candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def _requested_languages() -> list[str] | None:
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(variable)
        if not raw:
            continue
        languages: list[str] = []
        for value in raw.split(":"):
            normalized = value.strip().replace("-", "_")
            normalized = normalized.split(".", 1)[0].split("@", 1)[0]
            if normalized and normalized not in languages:
                languages.append(normalized)
        return languages or None
    return None


def _load_translation() -> gettext.NullTranslations:
    languages = _requested_languages()
    for locale_dir in _locale_dirs():
        try:
            return gettext.translation(
                DOMAIN,
                localedir=locale_dir,
                languages=languages,
                fallback=False,
            )
        except FileNotFoundError:
            continue
    return gettext.NullTranslations()


try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

_translation = _load_translation()
_ = _translation.gettext
