from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import total_ordering
from typing import Any, Callable

from pynextcloud_sync import VERSION


VERSION_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ehstbr/PyNextCloud-Sync/main/version.json"
)
RELEASES_URL = "https://github.com/ehstbr/PyNextCloud-Sync/releases/latest"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SUMMARY_CHARACTERS = 8_000
MAX_CHANGELOG_ITEMS = 100
MAX_CHANGELOG_ITEM_CHARACTERS = 2_000

_CORE_IDENTIFIER = re.compile(r"0|[1-9][0-9]*")
_IDENTIFIER = re.compile(r"[0-9A-Za-z-]+")
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z"
)


class UpdateManifestError(ValueError):
    """Raised when the remote update manifest is invalid or incomplete."""


@total_ordering
@dataclass(frozen=True, eq=False)
class SemanticVersion:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemanticVersion:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("Version must be a non-empty SemVer string.")
        core_and_suffix, plus, build_text = value.partition("+")
        if plus and (not build_text or "+" in build_text):
            raise ValueError("Invalid SemVer build metadata.")
        core_text, dash, prerelease_text = core_and_suffix.partition("-")
        if dash and not prerelease_text:
            raise ValueError("Invalid empty SemVer prerelease.")
        core = core_text.split(".")
        if len(core) != 3 or not all(_CORE_IDENTIFIER.fullmatch(item) for item in core):
            raise ValueError("Version must contain three numeric SemVer components.")
        prerelease = cls._parse_identifiers(
            prerelease_text if dash else "", prerelease=True
        )
        build = cls._parse_identifiers(build_text if plus else "", prerelease=False)
        return cls(*(int(item) for item in core), prerelease=prerelease, build=build)

    @staticmethod
    def _parse_identifiers(value: str, *, prerelease: bool) -> tuple[str, ...]:
        if not value:
            return ()
        identifiers = tuple(value.split("."))
        if not all(item and _IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Invalid SemVer identifier.")
        if prerelease and any(
            item.isdigit() and len(item) > 1 and item.startswith("0")
            for item in identifiers
        ):
            raise ValueError("Numeric prerelease identifiers cannot have leading zeroes.")
        return identifiers

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        own_core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if own_core != other_core:
            return own_core < other_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for own_identifier, other_identifier in zip(
            self.prerelease, other.prerelease
        ):
            if own_identifier == other_identifier:
                continue
            own_numeric = own_identifier.isdigit()
            other_numeric = other_identifier.isdigit()
            if own_numeric and other_numeric:
                return int(own_identifier) < int(other_identifier)
            if own_numeric != other_numeric:
                return own_numeric
            return own_identifier < other_identifier
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class UpdateManifest:
    version_text: str
    version: SemanticVersion
    mandatory: bool
    summary: str
    changelog: tuple[str, ...]
    released_at: datetime

    @property
    def released_at_utc_text(self) -> str:
        return self.released_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )


@dataclass(frozen=True)
class UpdateCheckResult:
    latest: UpdateManifest | None = None
    update_available: bool = False
    error: str | None = None


def parse_update_manifest(data: bytes) -> UpdateManifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise UpdateManifestError("The update manifest is too large.")
    try:
        decoded = data.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateManifestError("The update manifest is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise UpdateManifestError("The update manifest root must be an object.")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise UpdateManifestError("Unsupported or missing update manifest schema.")

    version_text = payload.get("version")
    try:
        version = SemanticVersion.parse(version_text)
    except (TypeError, ValueError) as exc:
        raise UpdateManifestError("The update manifest version is invalid.") from exc

    mandatory = payload.get("mandatory")
    if type(mandatory) is not bool:
        raise UpdateManifestError("The mandatory field must be a boolean.")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise UpdateManifestError("The update summary is missing or invalid.")
    summary = summary.strip()
    if len(summary) > MAX_SUMMARY_CHARACTERS:
        raise UpdateManifestError("The update summary is too long.")

    changelog_value = payload.get("changelog")
    if not isinstance(changelog_value, list) or not changelog_value:
        raise UpdateManifestError("The update changelog is missing or invalid.")
    if len(changelog_value) > MAX_CHANGELOG_ITEMS:
        raise UpdateManifestError("The update changelog contains too many items.")
    changelog: list[str] = []
    for item in changelog_value:
        if not isinstance(item, str) or not item.strip():
            raise UpdateManifestError("The update changelog contains an invalid item.")
        normalized_item = item.strip()
        if len(normalized_item) > MAX_CHANGELOG_ITEM_CHARACTERS:
            raise UpdateManifestError("An update changelog item is too long.")
        changelog.append(normalized_item)

    released_at_text = payload.get("released_at")
    if not isinstance(released_at_text, str) or not _UTC_TIMESTAMP.fullmatch(
        released_at_text
    ):
        raise UpdateManifestError("The release date must be an ISO 8601 UTC value.")
    try:
        released_at = datetime.fromisoformat(released_at_text[:-1] + "+00:00")
    except ValueError as exc:
        raise UpdateManifestError("The release date is invalid.") from exc
    if released_at.utcoffset() != timezone.utc.utcoffset(released_at):
        raise UpdateManifestError("The release date must use UTC.")

    return UpdateManifest(
        version_text=version_text,
        version=version,
        mandatory=mandatory,
        summary=summary,
        changelog=tuple(changelog),
        released_at=released_at,
    )


def evaluate_update(
    data: bytes,
    *,
    current_version: str = VERSION,
) -> UpdateCheckResult:
    latest = parse_update_manifest(data)
    try:
        installed = SemanticVersion.parse(current_version)
    except ValueError as exc:
        raise UpdateManifestError("The installed application version is invalid.") from exc
    return UpdateCheckResult(
        latest=latest,
        update_available=latest.version > installed,
    )


UpdateCallback = Callable[[UpdateCheckResult], None]


class UpdateChecker:
    def __init__(
        self,
        *,
        http: Any | None = None,
        url: str = VERSION_MANIFEST_URL,
    ) -> None:
        if http is None:
            from pynextcloud_sync.nextcloud.http import HttpClient

            http = HttpClient(timeout=8)
        self.http = http
        self.url = url
        self._cancellable: Any | None = None

    def check(
        self,
        callback: UpdateCallback,
        *,
        current_version: str = VERSION,
    ) -> None:
        self.cancel()
        completed_synchronously = False

        def finished(status: int, data: bytes, error: Exception | None) -> None:
            nonlocal completed_synchronously
            completed_synchronously = True
            self._cancellable = None
            if error is not None:
                callback(UpdateCheckResult(error=str(error)))
                return
            if status != 200:
                callback(UpdateCheckResult(error=f"HTTP status {status}"))
                return
            try:
                callback(evaluate_update(data, current_version=current_version))
            except UpdateManifestError as exc:
                callback(UpdateCheckResult(error=str(exc)))

        cancellable = self.http.request(
            "GET",
            self.url,
            finished,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
        )
        if not completed_synchronously:
            self._cancellable = cancellable

    def cancel(self) -> None:
        if self._cancellable is not None:
            self._cancellable.cancel()
            self._cancellable = None
