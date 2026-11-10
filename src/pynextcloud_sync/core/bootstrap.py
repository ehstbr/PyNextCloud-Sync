from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TypeVar

from pynextcloud_sync.core.bootstrap_checkpoint import (
    BootstrapCheckpoint,
    CheckpointError,
    directory_identity,
    snapshot_seal,
)
from pynextcloud_sync.core.bootstrap_progress import (
    BootstrapProgress,
    BootstrapProgressReporter,
    measure_download,
)
from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.safety import (
    InventoryEntry,
    InventorySnapshot,
    SafetyManifest,
    find_sync_databases,
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
    resumed: bool = False

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


class BootstrapPaused(BootstrapError):
    pass


JobResult = TypeVar("JobResult")
ProgressCallback = Callable[[BootstrapProgress], None]
AnalysisCallback = Callable[[BootstrapAnalysis | None, Exception | None], None]
ResultCallback = Callable[[BootstrapResult | None, Exception | None], None]


def _sha256(path: Path, reading: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            if reading:
                read += len(chunk)
                reading(read)
    return digest.hexdigest()


def _same_file(
    local_root: Path,
    remote_root: Path,
    local: InventoryEntry,
    remote: InventoryEntry,
    reading: Callable[[int], None] | None = None,
) -> bool:
    if local.size != remote.size:
        return False
    # Equal size and timestamp are useful for the summary, but are not proof of
    # equal content. Hashing avoids silently treating a same-size conflict as
    # identical during the one operation where correctness matters most.
    local_digest = _sha256(local_root / local.path, reading)

    def reading_remote(count: int) -> None:
        if reading:
            reading(local.size + count)

    return local_digest == _sha256(remote_root / remote.path, reading_remote if reading else None)


def analyze_inventories(
    local: InventorySnapshot,
    remote: InventorySnapshot,
    *,
    progress: BootstrapProgressReporter | None = None,
    check: Callable[[], None] | None = None,
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

    paths = sorted(local_paths | remote_paths, key=lambda value: (value.count("/"), value))
    if progress:
        progress.begin(_("Comparing both folders…"), total_items=len(paths))
    for index, path in enumerate(paths):
        if check:
            check()
        if progress:
            progress.update(items=index, current=path, file_bytes=0, file_size=0)
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
            local.root, remote.root, local_entry, remote_entry,
            _hash_progress(progress, check, index, path, local_entry.size),
        ):
            identical.append(path)
        else:
            conflicts.append(BootstrapConflict(path, "content", local_entry, remote_entry))

    if progress:
        progress.update(force=True, items=len(paths), current="", file_bytes=0, file_size=0)

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
    *,
    progress: BootstrapProgressReporter | None = None,
    check: Callable[[], None] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return missing, unexpected, and content/type mismatches."""

    expected_paths = set(expected.entries)
    actual_paths = set(actual.entries)
    missing = tuple(sorted(expected_paths - actual_paths))
    unexpected = tuple(sorted(actual_paths - expected_paths))
    mismatched: list[str] = []
    total = len(expected_paths | actual_paths)
    if progress:
        progress.begin(_("Verifying the final result…"), total_items=total)
    for index, path in enumerate(
        sorted(expected_paths & actual_paths), start=len(missing) + len(unexpected)
    ):
        if check:
            check()
        if progress:
            progress.update(items=index, current=path, file_bytes=0, file_size=0)
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
            _hash_progress(progress, check, index, path, expected_entry.size),
        ):
            mismatched.append(path)
    if progress:
        progress.update(force=True, items=total, current="", file_bytes=0, file_size=0)
    return missing, unexpected, tuple(mismatched)


def _hash_progress(
    progress: BootstrapProgressReporter | None,
    check: Callable[[], None] | None,
    index: int,
    path: str,
    size: int,
) -> Callable[[int], None] | None:
    if progress is None and check is None:
        return None

    def reading(count: int) -> None:
        if check:
            check()
        if progress:
            progress.update(items=index, current=path, file_bytes=count, file_size=2 * size)

    return reading


class BootstrapRunner:
    """Perform a protected first reconciliation around the official sync engine."""

    def __init__(
        self, config: Any, logger: Any, log: Callable[[str], None] | None = None
    ) -> None:
        self.config = config
        self.logger = logger
        self.log = log
        self.checkpoint = BootstrapCheckpoint(state_dir() / "bootstrap")
        self._cancelled = threading.Event()
        self._pause = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def has_pending_operation(self) -> bool:
        return self.checkpoint.path.exists()

    def _matcher(self) -> ExclusionMatcher:
        sync = self.config.data["sync"]
        return ExclusionMatcher(
            sync.get("exclude_patterns", []),
            sync.get("exclude_patterns_enabled", True),
        )

    def _start(
        self, job: Callable[[], JobResult],
        callback: Callable[[JobResult | None, Exception | None], None],
    ) -> None:
        if self._thread is not None:
            raise RuntimeError("A protected initialization job is already running.")
        self._cancelled.clear()
        self._pause.clear()

        def run() -> None:
            result, error = None, None
            try:
                result = job()
            except Exception as exc:
                error = exc
            finally:
                self._thread = None
            callback(result, error)

        self._thread = threading.Thread(target=run, name="pynextcloud-bootstrap", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None
            raise

    def analyze(
        self,
        password: str,
        progress: ProgressCallback,
        callback: AnalysisCallback,
        *,
        restart: bool = False,
        remote_etag: str | None = None,
    ) -> None:
        reporter = self._reporter(progress)
        self._start(
            lambda: self._analyze_worker(password, reporter, restart, remote_etag), callback
        )

    def _reporter(self, progress: ProgressCallback) -> BootstrapProgressReporter:
        return BootstrapProgressReporter(progress, self.log)

    def _account_key(self, local: Path, matcher: ExclusionMatcher) -> str:
        account = self.config.data["account"]
        return hashlib.sha256(json.dumps([
            account["server_url"], account["login_name"], str(local.resolve()),
            matcher.patterns if matcher.enabled else (),
        ]).encode()).hexdigest()

    def _inventory(
        self, root: Path, matcher: ExclusionMatcher, reporter: BootstrapProgressReporter,
        label: str, *, pausable: bool = False,
    ) -> InventorySnapshot:
        check = self._check_pause if pausable else self._raise_if_cancelled
        reporter.begin(label, counted=True)
        snapshot = scan_inventory(
            root, matcher, check=check, on_entry=lambda items: reporter.update(items=items)
        )
        reporter.update(force=True, items=len(snapshot.entries))
        return snapshot

    def _analyze_worker(
        self, password: str, reporter: BootstrapProgressReporter, restart: bool,
        remote_etag: str | None,
    ) -> BootstrapAnalysis:
        account = self.config.data["account"]
        local_root = Path(account["local_root"]).expanduser().absolute()
        matcher = self._matcher()
        reporter.begin(_("Creating an isolated safety snapshot…"))
        with self.checkpoint.lease() as lease:
            if restart:
                self._retire_checkpoint()
            saved = self.checkpoint.load()
            if saved and saved["phase"] == "apply":
                raise CheckpointError(
                    _("A previous application of the merge was interrupted. Run a new safety analysis before continuing.")
                )

            if saved:
                self._validate_local(saved, local_root, matcher)
            else:
                local_root.mkdir(parents=True, exist_ok=True)
            bootstrap_root = self.checkpoint.root.resolve()
            if (
                bootstrap_root.is_relative_to(local_root.resolve())
                or local_root.resolve().is_relative_to(bootstrap_root)
            ):
                raise BootstrapError(
                    _("Choose a local folder separate from the app’s protected storage.")
                )

            resumed = bool(saved and saved["phase"] == "ready")
            if resumed:
                if remote_etag and saved.get("remote_etag") not in (None, remote_etag):
                    raise CheckpointError(
                        _("Files on Nextcloud changed since this copy was downloaded. Download a new copy.")
                    )
                staging_root = self.checkpoint.stage(saved)
                remote = self._inventory(
                    staging_root, matcher, reporter, _("Checking the saved protected copy…"),
                    pausable=True,
                )
                if remote.errors or snapshot_seal(remote, self._check_pause) != saved.get("seal"):
                    raise CheckpointError(
                        _("The saved protected copy has changed. Download a new copy before continuing.")
                    )
            else:
                if saved:
                    self._retire_checkpoint()
                staging_root = Path(tempfile.mkdtemp(
                    prefix="protected-", dir=self.checkpoint.root
                ))
                try:
                    saved = {
                        "format": 1,
                        "phase": "download",
                        "stage": staging_root.name,
                        "stage_identity": directory_identity(staging_root),
                        "local_identity": directory_identity(local_root),
                        "account": self._account_key(local_root, matcher),
                        "remote_etag": remote_etag,
                    }
                    self.checkpoint.save(saved)
                    self._download(staging_root, password, matcher, reporter, lease)
                    remote = self._inventory(
                        staging_root, matcher, reporter, _("Inventorying the protected copy…")
                    )
                    if remote.errors:
                        raise BootstrapError(_("Some paths in the protected copy could not be read."))
                    if not any(path.suffix == ".db" for path in find_sync_databases(staging_root)):
                        raise BootstrapError(_("The protected copy has no synchronization journal."))
                    saved["seal"] = snapshot_seal(remote, self._raise_if_cancelled)
                    saved["phase"] = "ready"
                    self.checkpoint.save(saved)
                except Exception:
                    # A failed download is never fed back to the bidirectional engine.
                    self._remove_stage(staging_root)
                    self.checkpoint.clear()
                    raise

            self._check_pause()
            self._validate_local(saved, local_root, matcher)
            local = self._inventory(
                local_root, matcher, reporter, _("Inventorying the computer folder…"), pausable=True
            )
            local_only, remote_only, identical, conflicts, unsupported = analyze_inventories(
                local, remote, progress=reporter, check=self._check_pause
            )
            self._check_pause()
            try:
                free_bytes = shutil.disk_usage(local_root).free
            except OSError:
                free_bytes = 0
            return BootstrapAnalysis(
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
                resumed=resumed,
            )

    def _validate_local(self, saved: dict, root: Path, matcher: ExclusionMatcher) -> None:
        try:
            matches = (
                self._account_key(root, matcher) == saved.get("account")
                and directory_identity(root) == saved.get("local_identity")
            )
        except OSError:
            matches = False
        if not matches:
            raise CheckpointError(
                _("The account, local folder, or exclusions changed. Run a new safety analysis.")
            )

    def _retire_checkpoint(self) -> None:
        try:
            saved = self.checkpoint.load()
            if saved is None:
                return
            staging = self.checkpoint.stage(saved)
        except CheckpointError:
            self.checkpoint.clear()
            return

        if saved["phase"] == "apply":
            archive = ensure_private_directory(state_dir() / "safety-archives") / staging.name
            if archive.exists():
                raise CheckpointError(_("The interrupted merge could not be archived safely."))
            staging.rename(archive)
            self.logger.warning("Preserved interrupted protected merge in %s", archive)
        else:
            self._remove_stage(staging)
        self.checkpoint.clear()

    def _remove_stage(self, staging: Path) -> None:
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.logger.warning("Could not clean up protected staging: %s", exc)

    def _download(
        self, staging: Path, password: str, matcher: ExclusionMatcher,
        reporter: BootstrapProgressReporter, lease: int,
    ) -> None:
        reporter.begin(_("Contacting Nextcloud for the protected copy…"), downloading=True)
        stopped = threading.Event()

        def observe() -> None:
            delay = 1.0
            while not stopped.wait(delay):
                started = time.monotonic()
                files, size, partial = measure_download(staging, matcher, stopped)
                try:
                    free = shutil.disk_usage(staging).free
                except OSError:
                    free = None
                if not stopped.is_set():
                    message = (
                        _("Downloading a protected copy from Nextcloud…")
                        if files or partial else _("Contacting Nextcloud for the protected copy…")
                    )
                    reporter.update(
                        message=message, items=files, bytes_done=size,
                        partial_bytes=partial, free_bytes=free,
                    )
                delay = max(1.0, (time.monotonic() - started) * 19)

        observer = threading.Thread(target=observe, name="pynextcloud-bootstrap-meter", daemon=True)
        observer.start()
        try:
            self._run_sync(staging, password, lease)
        finally:
            stopped.set()
            observer.join()

    def execute(
        self,
        analysis: BootstrapAnalysis,
        password: str,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
        progress: ProgressCallback,
        callback: ResultCallback,
        *,
        remote_etag: str | None = None,
    ) -> None:
        reporter = self._reporter(progress)
        self._start(
            lambda: self._execute_worker(
                analysis, password, policy, decisions, reporter, remote_etag
            ),
            callback,
        )

    def _execute_worker(
        self,
        analysis: BootstrapAnalysis,
        password: str,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
        reporter: BootstrapProgressReporter,
        remote_etag: str | None,
    ) -> BootstrapResult:
        with self.checkpoint.lease() as lease:
            if analysis.has_blocking_errors:
                raise BootstrapError(
                    _("The protected initialization cannot continue while unreadable or unsupported paths exist.")
                )
            saved = self.checkpoint.load()
            if (
                saved is None or saved["phase"] != "ready"
                or self.checkpoint.stage(saved) != analysis.staging_root
            ):
                raise CheckpointError(_("Run a new safety analysis before applying the merge."))
            if analysis.resumed and (not remote_etag or saved.get("remote_etag") != remote_etag):
                raise CheckpointError(
                    _("The saved copy could not be verified against Nextcloud. Download a new copy before applying the merge.")
                )

            matcher = self._matcher()
            self._validate_local(saved, analysis.local_root, matcher)
            current_local = self._inventory(
                analysis.local_root, matcher, reporter, _("Rechecking the reviewed computer folder…")
            )
            if current_local.errors or current_local.entries != analysis.local.entries:
                raise BootstrapError(
                    _("The local folder changed after the analysis. Run the safety analysis again before applying anything.")
                )
            remote = self._inventory(
                analysis.staging_root, matcher, reporter, _("Checking the saved protected copy…")
            )
            if remote.errors or snapshot_seal(remote, self._raise_if_cancelled) != saved.get("seal"):
                raise CheckpointError(
                    _("The saved protected copy has changed. Download a new copy before continuing.")
                )

            self._raise_if_cancelled()
            saved["phase"] = "apply"
            self.checkpoint.save(saved)
            self._merge_into_staging(analysis, policy, decisions, reporter)
            reporter.begin(_("Applying the reviewed result to Nextcloud…"))
            self._run_sync(analysis.staging_root, password, lease)

            reporter.begin(_("Archiving previous synchronization state…"))
            archive = self._archive_sync_databases(analysis.local_root)
            self._apply_staging(analysis.staging_root, analysis.local_root, reporter)

            reporter.begin(_("Creating a clean synchronization baseline…"))
            self._run_sync(analysis.local_root, password, lease)
            final_snapshot = self._inventory(
                analysis.local_root, matcher, reporter, _("Inventorying the resulting computer folder…")
            )
            staged_snapshot = self._inventory(
                analysis.staging_root, matcher, reporter, _("Inventorying the reviewed result…")
            )
            if final_snapshot.errors or staged_snapshot.errors:
                raise BootstrapError(_("The final local verification could not read every path."))
            missing, unexpected, mismatched = inventory_differences(
                staged_snapshot, final_snapshot, progress=reporter, check=self._raise_if_cancelled
            )
            if missing or unexpected or mismatched:
                raise BootstrapError(
                    _("The final verification found differences; automatic synchronization remains blocked.")
                )

            reporter.begin(_("Saving the verified safety baseline…"))
            self._raise_if_cancelled()
            SafetyManifest().save(self.config.data["account"], final_snapshot)
            safety = self.config.data["safety"]
            previous = safety.copy()
            safety["bootstrap_complete"] = True
            safety["bootstrap_completed_at"] = datetime.now(timezone.utc).isoformat()
            safety.pop("bootstrap_mode", None)
            try:
                self.config.save(notify=False)
            except Exception:
                self.config.data["safety"] = previous
                raise
            # The baseline and completion flag are durable before disposing of
            # anything. A cleanup failure is logged after a successful apply.
            try:
                self.checkpoint.clear()
            except OSError as exc:
                self.logger.warning("Could not clear protected checkpoint: %s", exc)
            self._remove_stage(analysis.staging_root)
            return BootstrapResult(len(final_snapshot.files), archive)

    def _run_sync(self, root: Path, password: str, lease: int) -> None:
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
            with self._process_lock:
                self._raise_if_cancelled()
                process = subprocess.Popen(
                    spec.argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    pass_fds=(lease,),
                )
                self._process = process
        except OSError as exc:
            raise BootstrapError(_("Could not start nextcloudcmd: {error}").format(error=exc)) from exc
        try:
            with process:
                assert process.stdout is not None
                for raw_line in process.stdout:
                    line = self.logger.redactor.redact(raw_line.rstrip("\n"))
                    capture.feed(line)
                    self.logger.info("CMD %s", line)
                    if self.log:
                        self.log(line)
            exit_code = process.returncode
        finally:
            with self._process_lock:
                self._process = None
        self._raise_if_cancelled()
        if exit_code != 0 or capture.classification(exit_code) == "authentication":
            detail = capture.output.splitlines()[-1] if capture.output else _("No diagnostic output")
            raise BootstrapError(
                _("nextcloudcmd failed (exit {code}): {detail}").format(code=exit_code, detail=detail)
            )

    def _merge_into_staging(
        self,
        analysis: BootstrapAnalysis,
        policy: BootstrapPolicy,
        decisions: dict[str, BootstrapPolicy],
        reporter: BootstrapProgressReporter | None = None,
    ) -> None:
        total = len(analysis.local_only) + len(analysis.conflicts)
        if reporter:
            reporter.begin(
                _("Preparing the selected merge without discarding either version…"),
                total_items=total,
            )
        items = 0
        stage = analysis.staging_root
        local = analysis.local_root
        for relative in sorted(analysis.local_only, key=lambda item: (item.count("/"), item)):
            self._raise_if_cancelled()
            if reporter:
                reporter.update(items=items, current=relative)
            entry = analysis.local.entries[relative]
            self._copy_entry(local / relative, stage / relative, entry.kind)
            items += 1

        for conflict in analysis.conflicts:
            self._raise_if_cancelled()
            if reporter:
                reporter.update(items=items, current=conflict.path)
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
            items += 1
        if reporter:
            reporter.update(force=True, items=items, current="")

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

    def _apply_staging(
        self, staging: Path, local: Path, reporter: BootstrapProgressReporter,
    ) -> None:
        desired = self._inventory(
            staging, self._matcher(), reporter, _("Inventorying the reviewed result…")
        )
        if desired.errors or any(
            entry.kind not in {"file", "directory"} for entry in desired.entries.values()
        ):
            raise BootstrapError(_("The reviewed copy contains unreadable or unsupported paths."))
        reporter.begin(_("Copying the reviewed result to the computer…"), total_items=len(desired.entries))
        collision_archive: Path | None = None
        for index, (relative, entry) in enumerate(sorted(
            desired.entries.items(), key=lambda item: (item[0].count("/"), item[0])
        )):
            self._raise_if_cancelled()
            reporter.update(items=index, current=relative)
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
        reporter.update(force=True, items=len(desired.entries), current="")

    def pause(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._process_lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()

    def _check_pause(self) -> None:
        self._raise_if_cancelled()
        if self._pause.is_set():
            raise BootstrapPaused

    def _raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise BootstrapError(_("Protected initialization was cancelled."))
