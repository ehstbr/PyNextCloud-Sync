from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.safety import (
    InventoryEntry,
    InventorySnapshot,
    SafetyManifest,
    find_sync_databases,
    is_sync_database_name,
    scan_inventory,
)
from pynextcloud_sync.nextcloud.command import (
    BoundedOutputCapture,
    NextcloudCmdMissingError,
    build_command,
)
from pynextcloud_sync.util.paths import config_dir, ensure_private_directory, state_dir
from pynextcloud_sync.util.i18n import _


class BootstrapPolicy(str, Enum):
    MERGE_NEWEST = "merge_newest"
    NEXTCLOUD_FIRST = "nextcloud_first"
    COMPUTER_FIRST = "computer_first"
    REVIEW = "review"


@dataclass(frozen=True)
class BootstrapConflict:
    path: str
    kind: str
    local: InventoryEntry
    remote: InventoryEntry


@dataclass
class BootstrapAnalysis:
    local_root: Path
    staging_root: Path
    local: InventorySnapshot
    remote: InventorySnapshot
    local_only: tuple[str, ...]
    remote_only: tuple[str, ...]
    identical: tuple[str, ...]
    conflicts: tuple[BootstrapConflict, ...]
    legacy_databases: tuple[Path, ...]
    unsupported: tuple[str, ...]
    free_bytes: int

    @property
    def local_file_count(self) -> int:
        return len(self.local.files)

    @property
    def remote_file_count(self) -> int:
        return len(self.remote.files)

    @property
    def required_download_bytes(self) -> int:
        return sum(
            self.remote.entries[path].size
            for path in self.remote_only
            if self.remote.entries[path].kind == "file"
        )

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.local.errors or self.remote.errors or self.unsupported)


@dataclass(frozen=True)
class BootstrapResult:
    synchronized_files: int
    archived_database_directory: Path | None


class BootstrapError(RuntimeError):
    pass


ProgressCallback = Callable[[str], None]
AnalysisCallback = Callable[[BootstrapAnalysis | None, Exception | None], None]
ResultCallback = Callable[[BootstrapResult | None, Exception | None], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(
    local_root: Path,
    remote_root: Path,
    local: InventoryEntry,
    remote: InventoryEntry,
) -> bool:
    if local.size != remote.size:
        return False
    # Equal size and timestamp are useful for the summary, but are not proof of
    # equal content. Hashing avoids silently treating a same-size conflict as
    # identical during the one operation where correctness matters most.
    return _sha256(local_root / local.path) == _sha256(remote_root / remote.path)


def analyze_inventories(
    local: InventorySnapshot,
    remote: InventorySnapshot,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[BootstrapConflict, ...],
    tuple[str, ...],
]:
    local_paths = set(local.entries)
    remote_paths = set(remote.entries)
    local_only = local_paths - remote_paths
    remote_only = remote_paths - local_paths
    identical: list[str] = []
    conflicts: list[BootstrapConflict] = []
    unsupported: set[str] = {
        path
        for snapshot in (local, remote)
        for path, entry in snapshot.entries.items()
        if entry.kind in {"symlink", "special"}
    }
    type_conflict_roots: list[str] = []

    for path in sorted(local_paths | remote_paths, key=lambda value: (value.count("/"), value)):
        if any(path.startswith(f"{ancestor}/") for ancestor in type_conflict_roots):
            local_only.discard(path)
            remote_only.discard(path)
            continue
        local_entry = local.entries.get(path)
        remote_entry = remote.entries.get(path)
        if local_entry is None or remote_entry is None:
            continue
        if local_entry.kind != remote_entry.kind:
            conflicts.append(BootstrapConflict(path, "type", local_entry, remote_entry))
            type_conflict_roots.append(path)
        elif local_entry.kind == "directory":
            identical.append(path)
        elif local_entry.kind == "file" and _same_file(
            local.root, remote.root, local_entry, remote_entry
        ):
            identical.append(path)
        else:
            conflicts.append(BootstrapConflict(path, "content", local_entry, remote_entry))

    def outside_type_conflict(path: str) -> bool:
        return not any(path.startswith(f"{ancestor}/") for ancestor in type_conflict_roots)

    return (
        tuple(sorted(path for path in local_only if outside_type_conflict(path))),
        tuple(sorted(path for path in remote_only if outside_type_conflict(path))),
        tuple(sorted(identical)),
        tuple(conflicts),
        tuple(sorted(unsupported)),
    )


def inventory_differences(
    expected: InventorySnapshot,
    actual: InventorySnapshot,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return missing, unexpected, and content/type mismatches."""

    expected_paths = set(expected.entries)
    actual_paths = set(actual.entries)
    missing = tuple(sorted(expected_paths - actual_paths))
    unexpected = tuple(sorted(actual_paths - expected_paths))
    mismatched: list[str] = []
    for path in sorted(expected_paths & actual_paths):
        expected_entry = expected.entries[path]
        actual_entry = actual.entries[path]
        if (
            expected_entry.kind != actual_entry.kind
            or expected_entry.size != actual_entry.size
        ):
            mismatched.append(path)
        elif expected_entry.kind == "file" and not _same_file(
            expected.root,
            actual.root,
            expected_entry,
            actual_entry,
        ):
            mismatched.append(path)
    return missing, unexpected, tuple(mismatched)


class BootstrapRunner:
    """Perform a protected first reconciliation around the official sync engine."""

    def __init__(self, config: Any, logger: Any) -> None:
        self.config = config
        self.logger = logger
        self._cancelled = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _matcher(self) -> ExclusionMatcher:
        sync = self.config.data["sync"]
        return ExclusionMatcher(
            sync.get("exclude_patterns", []),
            sync.get("exclude_patterns_enabled", True),
        )

    def analyze(
        self,
        password: str,
        progress: ProgressCallback,
        callback: AnalysisCallback,
    ) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("A protected initialization job is already running.")
        self._cancelled.clear()
        self._thread = threading.Thread(
            target=self._analyze_worker,
            args=(password, progress, callback),
            name="pynextcloud-bootstrap-analysis",
            daemon=True,
        )
        self._thread.start()

    def _analyze_worker(
        self,
        password: str,
        progress: ProgressCallback,
        callback: AnalysisCallback,
    ) -> None:
        staging_root: Path | None = None
        try:
            account = self.config.data["account"]
            local_root = Path(account["local_root"]).expanduser().absolute()
            local_root.mkdir(parents=True, exist_ok=True)
            progress(_("Creating an isolated safety snapshot…"))
            bootstrap_parent = ensure_private_directory(state_dir() / "bootstrap")
            staging_root = Path(
                tempfile.mkdtemp(prefix="protected-", dir=bootstrap_parent)
            )
            staging_root.chmod(0o700)
            if any(staging_root.iterdir()):
                raise BootstrapError(_("The protected staging folder was not empty."))

            progress(_("Downloading a protected copy from Nextcloud…"))
            self._run_sync(staging_root, password)
            self._raise_if_cancelled()

            progress(_("Comparing paths, sizes, dates, and file contents…"))
            matcher = self._matcher()
            local = scan_inventory(local_root, matcher)
            remote = scan_inventory(staging_root, matcher)
            local_only, remote_only, identical, conflicts, unsupported = (
                analyze_inventories(local, remote)
            )
            try:
                free_bytes = shutil.disk_usage(local_root).free
            except OSError:
                free_bytes = 0
            analysis = BootstrapAnalysis(
                local_root=local_root,
                staging_root=staging_root,
                local=local,
                remote=remote,
                local_only=local_only,
                remote_only=remote_only,
                identical=identical,
                conflicts=conflicts,
                legacy_databases=find_sync_databases(local_root),
                unsupported=unsupported,
                free_bytes=free_bytes,
            )
            callback(analysis, None)
        except Exception as exc:
            if staging_root:
                self._cleanup_staging(staging_root)
            callback(None, exc)

    def execute(
        self,
        analysis: BootstrapAnalysis,
        password: str,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
        progress: ProgressCallback,
        callback: ResultCallback,
    ) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("A protected initialization job is already running.")
        self._cancelled.clear()
        self._thread = threading.Thread(
            target=self._execute_worker,
            args=(analysis, password, policy, decisions, progress, callback),
            name="pynextcloud-bootstrap-apply",
            daemon=True,
        )
        self._thread.start()

    def _execute_worker(
        self,
        analysis: BootstrapAnalysis,
        password: str,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
        progress: ProgressCallback,
        callback: ResultCallback,
    ) -> None:
        archive: Path | None = None
        try:
            if analysis.has_blocking_errors:
                raise BootstrapError(
                    _("The protected initialization cannot continue while unreadable or unsupported paths exist.")
                )
            self._raise_if_cancelled()
            current_local = scan_inventory(analysis.local_root, self._matcher())
            if current_local.errors or current_local.entries != analysis.local.entries:
                raise BootstrapError(
                    _("The local folder changed after the analysis. Run the safety analysis again before applying anything.")
                )
            progress(_("Preparing the selected merge without discarding either version…"))
            self._merge_into_staging(analysis, policy, decisions)

            progress(_("Applying the reviewed result to Nextcloud…"))
            self._run_sync(analysis.staging_root, password)
            self._raise_if_cancelled()

            progress(_("Archiving old synchronization state and updating the local folder…"))
            archive = self._archive_sync_databases(analysis.local_root)
            self._apply_staging(analysis.staging_root, analysis.local_root)

            progress(_("Creating a clean synchronization baseline…"))
            self._run_sync(analysis.local_root, password)
            self._raise_if_cancelled()

            matcher = self._matcher()
            final_snapshot = scan_inventory(analysis.local_root, matcher)
            staged_snapshot = scan_inventory(analysis.staging_root, matcher)
            if final_snapshot.errors or staged_snapshot.errors:
                raise BootstrapError(_("The final local verification could not read every path."))
            missing, unexpected, mismatched = inventory_differences(
                staged_snapshot, final_snapshot
            )
            if missing or unexpected or mismatched:
                raise BootstrapError(
                    _("The final verification found differences; automatic synchronization remains blocked.")
                )
            SafetyManifest().save(self.config.data["account"], final_snapshot)
            self._cleanup_staging(analysis.staging_root)
            callback(BootstrapResult(len(final_snapshot.files), archive), None)
        except Exception as exc:
            callback(None, exc)

    def _run_sync(self, root: Path, password: str) -> None:
        self._raise_if_cancelled()
        account = dict(self.config.data["account"])
        account["local_root"] = str(root)
        matcher = self._matcher()
        exclude_path = matcher.write_nextcloudcmd_file(config_dir() / "excludes.lst")
        try:
            spec = build_command(
                account,
                self.config.data["sync"],
                self.config.data["network"],
                password,
                exclude_path,
            )
        except NextcloudCmdMissingError as exc:
            raise BootstrapError(str(exc)) from exc
        environment = os.environ.copy()
        environment.update(spec.environment)
        capture = BoundedOutputCapture(max_lines=200)
        self.logger.info("Starting protected nextcloudcmd in %s", root)
        try:
            process = subprocess.Popen(
                spec.argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
        except OSError as exc:
            raise BootstrapError(f"Could not start nextcloudcmd: {exc}") from exc
        with self._process_lock:
            self._process = process
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = self.logger.redactor.redact(raw_line.rstrip("\n"))
                capture.feed(line)
                self.logger.info("CMD %s", line)
                if self._cancelled.is_set():
                    process.terminate()
                    break
            exit_code = process.wait()
        finally:
            with self._process_lock:
                self._process = None
        if self._cancelled.is_set():
            raise BootstrapError(_("Protected initialization was cancelled."))
        if exit_code != 0:
            detail = capture.output.splitlines()[-1] if capture.output else "No diagnostic output"
            raise BootstrapError(
                f"nextcloudcmd could not create the protected snapshot (exit {exit_code}): {detail}"
            )

    def _merge_into_staging(
        self,
        analysis: BootstrapAnalysis,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
    ) -> None:
        stage = analysis.staging_root
        local = analysis.local_root
        for relative in sorted(analysis.local_only, key=lambda item: (item.count("/"), item)):
            entry = analysis.local.entries[relative]
            self._copy_entry(local / relative, stage / relative, entry.kind)

        for conflict in analysis.conflicts:
            selected = decisions.get(conflict.path, policy)
            if selected == BootstrapPolicy.REVIEW:
                raise BootstrapError(f"No decision was recorded for {conflict.path}.")
            if selected == BootstrapPolicy.MERGE_NEWEST:
                selected = (
                    BootstrapPolicy.COMPUTER_FIRST
                    if conflict.local.modified_ns > conflict.remote.modified_ns
                    else BootstrapPolicy.NEXTCLOUD_FIRST
                )
            original = stage / conflict.path
            if selected == BootstrapPolicy.COMPUTER_FIRST:
                preserved = self._unique_alternative(stage, conflict.path, "Nextcloud copy")
                preserved.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original), str(preserved))
                self._copy_entry(
                    local / conflict.path,
                    original,
                    conflict.local.kind,
                    recursive=True,
                )
            else:
                preserved = self._unique_alternative(stage, conflict.path, "Computer copy")
                self._copy_entry(
                    local / conflict.path,
                    preserved,
                    conflict.local.kind,
                    recursive=True,
                )

    @staticmethod
    def _copy_entry(
        source: Path,
        destination: Path,
        kind: str,
        *,
        recursive: bool = False,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if kind == "directory":
            if recursive:
                shutil.copytree(source, destination, copy_function=shutil.copy2)
            else:
                destination.mkdir(parents=True, exist_ok=True)
            return
        if kind != "file":
            raise BootstrapError(f"Unsupported local path type: {source}")
        if destination.exists() and destination.is_dir():
            raise BootstrapError(f"A folder blocks the file destination: {destination}")
        shutil.copy2(source, destination)

    @staticmethod
    def _unique_alternative(root: Path, relative: str, label: str) -> Path:
        source = Path(relative)
        stamp = datetime.now().strftime("%Y-%m-%d")
        suffix = source.suffix if source.suffix and not (root / relative).is_dir() else ""
        stem = source.name[: -len(suffix)] if suffix else source.name
        for index in range(1, 10_000):
            counter = "" if index == 1 else f" {index}"
            candidate_name = f"{stem} ({label} {stamp}{counter}){suffix}"
            candidate = root / source.parent / candidate_name
            if not candidate.exists():
                return candidate
        raise BootstrapError(f"Could not create a preserved name for {relative}.")

    def _archive_sync_databases(self, root: Path) -> Path | None:
        databases = find_sync_databases(root)
        if not databases:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = ensure_private_directory(state_dir() / "safety-archives" / stamp)
        for database in databases:
            shutil.move(str(database), str(archive / database.name))
        self.logger.warning(
            "Archived %s previous synchronization database files in %s",
            len(databases),
            archive,
        )
        return archive

    def _apply_staging(self, staging: Path, local: Path) -> None:
        matcher = self._matcher()
        desired = scan_inventory(staging, matcher)
        collision_archive: Path | None = None
        for relative, entry in sorted(
            desired.entries.items(), key=lambda item: (item[0].count("/"), item[0])
        ):
            source = staging / relative
            target = local / relative
            target_kind = None
            if target.exists() or target.is_symlink():
                if target.is_symlink():
                    target_kind = "symlink"
                elif target.is_dir():
                    target_kind = "directory"
                else:
                    target_kind = "file"
            if target_kind and target_kind != entry.kind:
                if collision_archive is None:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    collision_archive = ensure_private_directory(
                        state_dir() / "safety-archives" / f"collisions-{stamp}"
                    )
                archived = collision_archive / relative
                archived.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(archived))
            self._copy_entry(source, target, entry.kind)

    def cancel(self) -> None:
        self._cancelled.set()
        with self._process_lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def cleanup(self, analysis: BootstrapAnalysis | None) -> None:
        if analysis:
            self._cleanup_staging(analysis.staging_root)

    @staticmethod
    def _cleanup_staging(path: Path) -> None:
        parent = (state_dir() / "bootstrap").expanduser().absolute()
        candidate = path.expanduser().absolute()
        if candidate.parent == parent and candidate.name.startswith("protected-"):
            shutil.rmtree(candidate, ignore_errors=True)

    def _raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise BootstrapError(_("Protected initialization was cancelled."))
