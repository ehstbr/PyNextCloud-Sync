from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.util.paths import ensure_private_directory, state_dir
from pynextcloud_sync.util.i18n import _


MANIFEST_FORMAT = 1
ROOT_ID_XATTR = b"user.pynextcloud_sync_root_id"
SYNC_DATABASE_RE = re.compile(r"^\.?_?sync.*\.db(?:[-.].*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    kind: str
    size: int
    modified_ns: int


@dataclass
class InventorySnapshot:
    root: Path
    entries: dict[str, InventoryEntry] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def files(self) -> dict[str, InventoryEntry]:
        return {
            path: entry
            for path, entry in self.entries.items()
            if entry.kind != "directory"
        }

    @property
    def directories(self) -> dict[str, InventoryEntry]:
        return {
            path: entry
            for path, entry in self.entries.items()
            if entry.kind == "directory"
        }

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.files.values())


@dataclass(frozen=True)
class SafetyAlert:
    reason: str
    message: str
    missing_paths: tuple[str, ...] = ()
    previous_files: int = 0
    current_files: int = 0

    @property
    def missing_count(self) -> int:
        return len(self.missing_paths)

    @property
    def can_approve_once(self) -> bool:
        """Allow bypass only for an explicit, observable deletion decision.

        Structural failures (missing/replaced roots, missing databases, unreadable
        trees, or missing manifests) must always go through protected recovery.
        """

        return self.reason in {"folder_emptied", "mass_local_deletion"}


def is_sync_database_name(name: str) -> bool:
    return bool(SYNC_DATABASE_RE.match(name))


def find_sync_databases(root: Path) -> tuple[Path, ...]:
    try:
        return tuple(
            sorted(
                (
                    item
                    for item in root.iterdir()
                    if item.is_file() and is_sync_database_name(item.name)
                ),
                key=lambda item: item.name,
            )
        )
    except OSError:
        return ()


def scan_inventory(root: Path, matcher: ExclusionMatcher) -> InventorySnapshot:
    """Inventory a sync tree without following links or sync journal files."""

    root = root.expanduser().absolute()
    snapshot = InventorySnapshot(root=root)
    if not root.exists():
        snapshot.errors.append(f"The local synchronization folder does not exist: {root}")
        return snapshot
    if not root.is_dir():
        snapshot.errors.append(f"The local synchronization path is not a folder: {root}")
        return snapshot

    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, relative_directory = stack.pop()
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            snapshot.errors.append(f"Could not read {directory}: {exc}")
            continue
        for child in children:
            name = child.name
            if is_sync_database_name(name) or matcher.matches_name(name):
                continue
            relative = f"{relative_directory}/{name}" if relative_directory else name
            try:
                details = child.stat(follow_symlinks=False)
            except OSError as exc:
                snapshot.errors.append(f"Could not inspect {child.path}: {exc}")
                continue

            mode = details.st_mode
            if stat.S_ISLNK(mode):
                kind = "symlink"
                size = 0
            elif stat.S_ISDIR(mode):
                kind = "directory"
                size = 0
            elif stat.S_ISREG(mode):
                kind = "file"
                size = int(details.st_size)
            else:
                kind = "special"
                size = 0
            snapshot.entries[relative] = InventoryEntry(
                path=relative,
                kind=kind,
                size=size,
                modified_ns=int(details.st_mtime_ns),
            )
            if kind == "directory":
                stack.append((Path(child.path), relative))
    return snapshot


def account_fingerprint(account: dict[str, Any]) -> str:
    identity = "\n".join(
        (
            str(account.get("server_url", "")).rstrip("/").casefold(),
            str(account.get("login_name", "")).casefold(),
            str(Path(str(account.get("local_root", ""))).expanduser().absolute()),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _read_root_id(root: Path) -> str | None:
    try:
        return os.getxattr(root, ROOT_ID_XATTR).decode("ascii")
    except (AttributeError, OSError, UnicodeDecodeError):
        return None


def ensure_root_id(root: Path) -> str | None:
    existing = _read_root_id(root)
    if existing:
        return existing
    value = str(uuid.uuid4())
    try:
        os.setxattr(root, ROOT_ID_XATTR, value.encode("ascii"))
        return value
    except (AttributeError, OSError):
        return None


class SafetyManifest:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "safety-manifest.json")

    def load(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("format") != MANIFEST_FORMAT:
            return None
        return payload

    def save(
        self,
        account: dict[str, Any],
        snapshot: InventorySnapshot,
    ) -> dict[str, Any]:
        root = snapshot.root
        root.mkdir(parents=True, exist_ok=True)
        root_stat = root.stat()
        payload = {
            "format": MANIFEST_FORMAT,
            "account_fingerprint": account_fingerprint(account),
            "local_root": str(root),
            "root_id": ensure_root_id(root),
            "root_device": int(root_stat.st_dev),
            "root_inode": int(root_stat.st_ino),
            "files": sorted(snapshot.files),
            "sync_databases": [item.name for item in find_sync_databases(root)],
        }
        ensure_private_directory(self.path.parent)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(self.path.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return payload


class SafetyGuard:
    """Block a sync when the local tree no longer resembles the last good tree."""

    def __init__(self, config: Any, logger: Any, manifest: SafetyManifest | None = None) -> None:
        self.config = config
        self.logger = logger
        self.manifest = manifest or SafetyManifest()

    def _matcher(self) -> ExclusionMatcher:
        sync = self.config.data["sync"]
        return ExclusionMatcher(
            sync.get("exclude_patterns", []),
            sync.get("exclude_patterns_enabled", True),
        )

    def check(self) -> SafetyAlert | None:
        account = self.config.data.get("account")
        safety = self.config.data.get("safety", {})
        if not account or not safety.get("guard_enabled", True):
            return None
        manifest = self.manifest.load()
        if manifest is None:
            return SafetyAlert(
                "manifest_missing",
                _("The safety baseline is missing. Review both sides before synchronizing."),
            )
        if manifest.get("account_fingerprint") != account_fingerprint(account):
            return SafetyAlert(
                "account_changed",
                _("The synchronized account or local folder changed since the last safe baseline."),
            )

        root = Path(account["local_root"]).expanduser().absolute()
        if not root.exists() or not root.is_dir():
            return SafetyAlert(
                "folder_missing",
                _("The local synchronization folder is missing or unavailable."),
                previous_files=len(manifest.get("files", [])),
            )

        try:
            root_stat = root.stat()
        except OSError as exc:
            return SafetyAlert("folder_unreadable", _("The local folder cannot be read: {error}").format(error=exc))
        expected_root_id = manifest.get("root_id")
        current_root_id = _read_root_id(root)
        if expected_root_id and current_root_id != expected_root_id:
            return SafetyAlert(
                "folder_replaced",
                _("The local synchronization folder appears to have been replaced or remounted."),
            )
        if not expected_root_id and (
            int(manifest.get("root_device", -1)) != int(root_stat.st_dev)
            or int(manifest.get("root_inode", -1)) != int(root_stat.st_ino)
        ):
            return SafetyAlert(
                "folder_replaced",
                _("The local synchronization folder identity changed since the last safe baseline."),
            )

        snapshot = scan_inventory(root, self._matcher())
        if snapshot.errors:
            return SafetyAlert(
                "scan_failed",
                _("Some local paths could not be read. Synchronization is blocked to avoid treating them as deleted."),
            )

        previous = set(str(path) for path in manifest.get("files", []))
        current = set(snapshot.files)
        missing = tuple(sorted(previous - current))
        previous_count = len(previous)
        current_count = len(current)
        if previous_count and not current_count:
            return SafetyAlert(
                "folder_emptied",
                _("A previously populated synchronization folder is now empty."),
                missing,
                previous_count,
                current_count,
            )

        expected_databases = tuple(manifest.get("sync_databases", []))
        if expected_databases and not find_sync_databases(root):
            return SafetyAlert(
                "database_missing",
                _("The Nextcloud synchronization state database disappeared unexpectedly."),
                missing,
                previous_count,
                current_count,
            )

        count_limit = max(1, int(safety.get("deletion_count_threshold", 10)))
        percent_limit = max(
            1.0, min(100.0, float(safety.get("deletion_percent_threshold", 20)))
        )
        missing_percent = (len(missing) * 100.0 / previous_count) if previous_count else 0.0
        if missing and (len(missing) >= count_limit or missing_percent >= percent_limit):
            return SafetyAlert(
                "mass_local_deletion",
                _("An unusual number of local files disappeared and could be deleted from Nextcloud."),
                missing,
                previous_count,
                current_count,
            )
        return None

    def record_current(self) -> bool:
        account = self.config.data.get("account")
        if not account:
            return False
        snapshot = scan_inventory(Path(account["local_root"]), self._matcher())
        if snapshot.errors:
            self.logger.error(
                "Could not update the safety baseline: %s", "; ".join(snapshot.errors)
            )
            return False
        self.manifest.save(account, snapshot)
        self.logger.info("Safety baseline updated with %s local files.", len(snapshot.files))
        return True
