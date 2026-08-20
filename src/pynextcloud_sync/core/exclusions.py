from __future__ import annotations

import fnmatch
from pathlib import Path


DEFAULT_PATTERNS = (
    ".DS_Store",
    "Thumbs.db",
    "ehthumbs.db",
    "Desktop.ini",
    "desktop.ini",
    "~$*",
    "*.swp",
    "*.swo",
    "*~",
    ".nextcloudsync.log",
)


class InvalidPattern(ValueError):
    pass


def validate_pattern(pattern: str) -> str:
    candidate = pattern.strip()
    if not candidate:
        raise InvalidPattern("Pattern cannot be empty.")
    if "/" in candidate or "\\" in candidate or ".." in candidate:
        raise InvalidPattern("Folder and path patterns are not supported.")
    if candidate in {"*", ".*", "*.*"}:
        raise InvalidPattern("This pattern is too broad and could hide user files.")
    if "\0" in candidate or len(candidate) > 255:
        raise InvalidPattern("Pattern is invalid or too long.")
    return candidate


class ExclusionMatcher:
    def __init__(self, patterns: list[str] | tuple[str, ...], enabled: bool = True) -> None:
        self.enabled = enabled
        self.patterns = tuple(validate_pattern(item) for item in patterns)

    def matches_name(self, name: str) -> bool:
        if not self.enabled:
            return False
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.patterns)

    def matches_path(self, path: str | Path) -> bool:
        return self.matches_name(Path(path).name)

    def write_nextcloudcmd_file(self, destination: Path) -> Path | None:
        if not self.enabled or not self.patterns:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text("\n".join(self.patterns) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(destination)
        return destination
