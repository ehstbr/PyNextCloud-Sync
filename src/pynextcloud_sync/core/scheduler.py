from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Callable

from gi.repository import GLib

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.state import AppState, StateController
from pynextcloud_sync.core.safety import SafetyAlert, SafetyGuard
from pynextcloud_sync.core.sync_run_marker import SyncRunMarker
from pynextcloud_sync.core.triggers import CoalescingQueue, Trigger, manual_only
from pynextcloud_sync.nextcloud.command import NextcloudCmdMissingError, build_command
from pynextcloud_sync.nextcloud.credentials import KeyringLockedError
from pynextcloud_sync.util.paths import config_dir
from pynextcloud_sync.util.i18n import _

from .sync_engine import SyncEngine, SyncResult


class SyncScheduler:
    DEBOUNCE_MS = 2000
    COOLDOWN_SECONDS = 4

    def __init__(
        self,
        config: Any,
        credentials: Any,
        engine: SyncEngine,
        state: StateController,
        logger: Any,
        on_completed: Callable[[SyncResult], None] | None = None,
        on_safety_alert: Callable[[SafetyAlert], None] | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.engine = engine
        self.state = state
        self.logger = logger
        self.on_completed = on_completed
        self.on_safety_alert = on_safety_alert
        self.queue = CoalescingQueue()
        self.online = True
        self.user_paused = False
        self.battery_paused = False
        self.local_dirty = False
        self.remote_pending = False
        self._debounce_source = 0
        self._start_source = 0
        self._cooldown_source = 0
        self._preparing = False
        self._safety_checking = False
        self._safety_bypass_once = False
        self.safety_alert: SafetyAlert | None = None
        self.safety_guard = SafetyGuard(config, logger)
        self.run_marker = SyncRunMarker()
        self._run_marker_active = False
        self._keyring_locked = False
        self._authentication_required = False
        self._stopped = False
        self._feedback_followup_pending = False
        self._inotify_during_sync = False

    @property
    def paused(self) -> bool:
        return self.user_paused or self.battery_paused

    @property
    def manual_only(self) -> bool:
        return manual_only(self.config.data["sync"])

    @property
    def keyring_locked(self) -> bool:
        return self._keyring_locked

    @property
    def authentication_required(self) -> bool:
        return self._authentication_required

    def authentication_restored(self) -> None:
        self._authentication_required = False
        self._keyring_locked = False
        self._set_idle_state()

    def authentication_rejected(self) -> None:
        self._authentication_required = True
        self.state.set(
            AppState.AUTH_REQUIRED,
            _("Reconnect the Nextcloud account to resume synchronization"),
        )

    def request(self, trigger: Trigger) -> None:
        if self._stopped:
            return
        if self.safety_alert and not self._safety_bypass_once:
            self.queue.add(trigger)
            self.state.set(AppState.SAFETY_REVIEW, _("Safety review required"))
            self.logger.warning(
                "Synchronization remains blocked by the safety guard: %s",
                self.safety_alert.reason,
            )
            return
        if self._authentication_required:
            self.queue.add(trigger)
            self.state.set(
                AppState.AUTH_REQUIRED,
                _("Reconnect the Nextcloud account to resume synchronization"),
            )
            self.logger.info(
                "Synchronization deferred until the Nextcloud account is reconnected: %s",
                trigger.value,
            )
            return
        if self.engine.running or self._preparing:
            if trigger == Trigger.LOCAL_INOTIFY:
                self._inotify_during_sync = True
            self.queue.add(trigger)
            self.logger.info("Synchronization request coalesced: %s", trigger.value)
            return
        if self.paused and trigger != Trigger.MANUAL:
            if trigger in {Trigger.LOCAL_INOTIFY, Trigger.LOCAL_INTERVAL, Trigger.LOCAL_RECOVERY}:
                self.local_dirty = True
            else:
                self.remote_pending = True
            self.logger.info("Synchronization deferred while paused: %s", trigger.value)
            return
        if not self.online:
            self.queue.add(trigger)
            self.state.set(AppState.OFFLINE, _("Waiting for a network connection"))
            self.logger.info("Synchronization deferred while offline: %s", trigger.value)
            return
        if self._keyring_locked and trigger != Trigger.MANUAL:
            self.queue.add(trigger)
            self.state.set(AppState.KEYRING_LOCKED, _("Password keyring is locked"))
            self.logger.info(
                "Synchronization deferred while the password keyring is locked: %s",
                trigger.value,
            )
            return
        self.queue.add(trigger)
        if self._keyring_locked and trigger == Trigger.MANUAL:
            # Begin the explicit unlock attempt immediately. This ensures any
            # simultaneous notify_push lookup joins the same native prompt.
            self._start()
        elif trigger == Trigger.LOCAL_INOTIFY:
            self._schedule_debounce()
        else:
            self._schedule_start()

    def _schedule_debounce(self) -> None:
        if self._debounce_source:
            GLib.source_remove(self._debounce_source)
        self.state.set(AppState.SYNC_QUEUED, _("Waiting for local changes to settle"))
        self._debounce_source = GLib.timeout_add(self.DEBOUNCE_MS, self._debounce_elapsed)

    def _debounce_elapsed(self) -> bool:
        self._debounce_source = 0
        self._schedule_start()
        return GLib.SOURCE_REMOVE

    def _schedule_start(self) -> None:
        if (
            self._stopped
            or self._debounce_source
            or self._start_source
            or self._cooldown_source
            or self._preparing
            or self._safety_checking
            or self.engine.running
        ):
            return
        self.state.set(AppState.SYNC_QUEUED, _("Synchronization scheduled"))
        self._start_source = GLib.idle_add(self._start)

    def _start(self) -> bool:
        self._start_source = 0
        if self._stopped or self._preparing or self.engine.running or not self.queue or not self.online:
            return GLib.SOURCE_REMOVE
        reasons = self.queue.take()
        if self.paused and Trigger.MANUAL not in reasons:
            self.local_dirty = True
            return GLib.SOURCE_REMOVE
        account = self.config.data.get("account")
        if not account:
            self.state.set(AppState.UNCONFIGURED)
            return GLib.SOURCE_REMOVE
        reason_text = ", ".join(sorted(reason.value for reason in reasons))
        self.logger.info("Synchronization triggers: %s", reason_text)
        safety = self.config.data.get("safety")
        if safety and safety.get("guard_enabled", True) and not self._safety_bypass_once:
            if self.run_marker.pending_for(account):
                self.logger.warning(
                    "A previous synchronization did not reach a committed safety baseline; validating the last known-good baseline before recovery."
                )
            self._preparing = True
            self._safety_checking = True
            self.state.set(AppState.SYNC_QUEUED, _("Checking the safety baseline…"))

            def check_worker() -> None:
                try:
                    alert = self.safety_guard.check()
                    error = None
                except Exception as exc:
                    alert = None
                    error = exc
                GLib.idle_add(
                    lambda: self._safety_checked(alert, error, account, reasons)
                )

            threading.Thread(
                target=check_worker,
                name="pynextcloud-safety-check",
                daemon=True,
            ).start()
            return GLib.SOURCE_REMOVE
        self._safety_bypass_once = False
        self._prepare_sync(account, reasons)
        return GLib.SOURCE_REMOVE

    def _safety_checked(
        self,
        alert: SafetyAlert | None,
        error: Exception | None,
        account: dict[str, Any],
        reasons: set[Trigger],
    ) -> bool:
        if self._stopped:
            return GLib.SOURCE_REMOVE
        self._safety_checking = False
        self._preparing = False
        if error:
            alert = SafetyAlert(
                "guard_failed",
                "The safety check failed, so synchronization was blocked.",
            )
            self.logger.error("Safety guard failed: %s", error)
        if alert:
            self.safety_alert = alert
            for reason in reasons:
                self.queue.add(reason)
            self.state.set(AppState.SAFETY_REVIEW, _(alert.message))
            self.logger.critical("Synchronization blocked by safety guard: %s", alert.reason)
            if self.on_safety_alert:
                self.on_safety_alert(alert)
            return GLib.SOURCE_REMOVE
        self._prepare_sync(account, reasons)
        return GLib.SOURCE_REMOVE

    def _prepare_sync(
        self,
        account: dict[str, Any],
        reasons: set[Trigger],
    ) -> None:
        self.state.set(AppState.SYNCING, _("Synchronizing files…"))
        self._preparing = True

        def secret_ready(password: str | None, error: Exception | None) -> None:
            if self._stopped:
                return
            self._preparing = False
            if error:
                if isinstance(error, KeyringLockedError):
                    self._keyring_locked = True
                    self.state.set(AppState.KEYRING_LOCKED, _("Password keyring is locked"))
                else:
                    self._keyring_locked = False
                    self.state.set(AppState.AUTH_REQUIRED, _("Could not read the account credential"))
                self.logger.error("Credential lookup failed: %s", error)
                return
            if not password:
                self._keyring_locked = False
                self._authentication_required = True
                self.state.set(AppState.AUTH_REQUIRED, _("No stored credential was found"))
                self.logger.error(
                    "Credential lookup returned no stored item for the configured account."
                )
                return
            self._keyring_locked = False
            self.logger.add_secret(password)
            sync = self.config.data["sync"]
            matcher = ExclusionMatcher(
                sync.get("exclude_patterns", []), sync.get("exclude_patterns_enabled", True)
            )
            exclude_path = matcher.write_nextcloudcmd_file(config_dir() / "excludes.lst")
            try:
                spec = build_command(
                    account,
                    sync,
                    self.config.data["network"],
                    password,
                    exclude_path,
                )
            except NextcloudCmdMissingError as exc:
                self.state.set(AppState.ERROR, str(exc))
                self.logger.error(exc)
                return
            safety = self.config.data.get("safety")
            if safety and safety.get("guard_enabled", True):
                try:
                    self.run_marker.begin(account)
                    self._run_marker_active = True
                except OSError as exc:
                    self.state.set(AppState.ERROR, _("Synchronization failed — view the log"))
                    self.logger.error(
                        "Synchronization blocked because the run marker could not be persisted: %s",
                        exc,
                    )
                    return
            feedback_followup = self._feedback_followup_pending
            self._feedback_followup_pending = False
            self.engine.run(
                spec,
                lambda result: self._finished(result, reasons, feedback_followup),
            )

        self.credentials.lookup(account["server_url"], account["login_name"], secret_ready)

    def _finished(
        self,
        result: SyncResult,
        reasons: set[Trigger],
        feedback_followup: bool = False,
    ) -> None:
        if self._stopped:
            return
        self.config.data["runtime"]["last_exit_code"] = result.exit_code
        self.logger.info("nextcloudcmd exited with code %s after %.1f seconds.", result.exit_code, result.duration)
        if result.successful:
            self.config.data["runtime"]["last_successful_sync"] = dt.datetime.now(
                dt.timezone.utc
            ).isoformat()
            if result.classification == "conflict":
                self.state.set(AppState.IDLE_OK, _("Synchronized with conflicts — review the log"))
            else:
                self._set_idle_state()
            self.logger.info("Synchronization completed successfully.")
            self._preparing = True

            def record_baseline() -> None:
                recorded = False
                try:
                    recorded = self.safety_guard.record_current()
                except Exception as exc:
                    self.logger.error("Could not commit the safety baseline: %s", exc)
                finally:
                    GLib.idle_add(self._baseline_recorded, recorded)

            threading.Thread(
                target=record_baseline,
                name="pynextcloud-safety-record",
                daemon=True,
            ).start()
        elif result.classification == "authentication":
            self.authentication_rejected()
            self.logger.error("Synchronization failed because authentication was rejected.")
        else:
            self.state.set(AppState.ERROR, _("Synchronization failed — view the log"))
            self.logger.error("Synchronization failed with exit code %s.", result.exit_code)
        try:
            self.config.save(notify=False)
        except Exception as exc:
            self.logger.error("Could not save runtime state: %s", exc)
        if self.on_completed:
            self.on_completed(result)

        queued = bool(self.queue)
        if self._inotify_during_sync:
            if feedback_followup:
                # Suppress only the local feedback from the reconciliation itself.
                # Manual, remote, resume, and network triggers must remain queued.
                self.queue.discard(Trigger.LOCAL_INOTIFY)
            else:
                self._feedback_followup_pending = True
                self.queue.add(Trigger.LOCAL_INOTIFY)
            queued = bool(self.queue)
        self._inotify_during_sync = False
        self._cooldown_source = GLib.timeout_add_seconds(
            self.COOLDOWN_SECONDS, self._cooldown_finished, queued
        )

    def _baseline_recorded(self, recorded: bool) -> bool:
        self._preparing = False
        if self._run_marker_active:
            if recorded:
                try:
                    self.run_marker.clear()
                    self._run_marker_active = False
                except OSError as exc:
                    self.logger.error(
                        "Could not clear the completed synchronization run marker: %s", exc
                    )
            else:
                self.logger.warning(
                    "Synchronization run marker retained because the new safety baseline was not committed."
                )
        if (
            not self._stopped
            and not self._cooldown_source
            and self.queue
            and self.online
            and not self.paused
        ):
            self._schedule_start()
        return GLib.SOURCE_REMOVE

    def _cooldown_finished(self, run_pending: bool) -> bool:
        self._cooldown_source = 0
        if self._stopped:
            return GLib.SOURCE_REMOVE
        if (
            run_pending
            and self.queue
            and self.online
            and not self.paused
            and not self._authentication_required
        ):
            self._schedule_start()
        else:
            if not self.paused:
                self._set_idle_state()
        return GLib.SOURCE_REMOVE

    def set_user_paused(self, paused: bool) -> None:
        self.user_paused = paused
        if paused:
            self.state.set(AppState.PAUSED_USER, _("Synchronization is paused"))
        else:
            should_reconcile = self.local_dirty or self.remote_pending or bool(self.queue)
            self.local_dirty = self.remote_pending = False
            if should_reconcile and not self.manual_only:
                self.request(Trigger.RESUME)
            else:
                self._set_idle_state()

    def set_battery_paused(self, paused: bool) -> None:
        was_paused = self.battery_paused
        self.battery_paused = paused
        if paused:
            message = _("Will pause after the current synchronization") if self.engine.running else _("Paused on battery")
            self.state.set(AppState.PAUSED_BATTERY, message)
        elif was_paused and not self.user_paused:
            should_reconcile = self.local_dirty or self.remote_pending or bool(self.queue)
            self.local_dirty = self.remote_pending = False
            if should_reconcile and not self.manual_only:
                self.request(Trigger.RESUME)
            else:
                self._set_idle_state()

    def set_online(self, online: bool) -> None:
        was_online = self.online
        self.online = online
        if not online:
            self.state.set(AppState.OFFLINE, _("Waiting for a network connection"))
        elif not was_online:
            if self.queue or not self.manual_only:
                self.request(Trigger.NETWORK_RESTORED)
            else:
                self._set_idle_state()

    def _set_idle_state(self) -> None:
        if self.safety_alert:
            self.state.set(AppState.SAFETY_REVIEW, _("Safety review required"))
        elif self._authentication_required:
            self.state.set(
                AppState.AUTH_REQUIRED,
                _("Reconnect the Nextcloud account to resume synchronization"),
            )
        elif self.user_paused:
            self.state.set(AppState.PAUSED_USER, _("Synchronization is paused"))
        elif self.battery_paused:
            self.state.set(AppState.PAUSED_BATTERY, _("Paused on battery"))
        elif not self.online:
            self.state.set(AppState.OFFLINE, _("Waiting for a network connection"))
        elif self.manual_only:
            self.state.set(AppState.IDLE_MANUAL_ONLY, _("Automatic synchronization is off"))
        else:
            self.state.set(AppState.IDLE_OK, _("Synchronized"))

    def approve_safety_once(self) -> None:
        if not self.safety_alert or not self.safety_alert.can_approve_once:
            if self.safety_alert:
                self.logger.warning(
                    "Safety alert cannot be bypassed and requires protected recovery: %s",
                    self.safety_alert.reason,
                )
            return
        self.logger.warning(
            "The user approved one synchronization despite safety alert: %s",
            self.safety_alert.reason,
        )
        self.safety_alert = None
        self._safety_bypass_once = True
        self.request(Trigger.MANUAL)

    def stop(self) -> None:
        self._stopped = True
        for attribute in ("_debounce_source", "_start_source", "_cooldown_source"):
            source = getattr(self, attribute)
            if source:
                GLib.source_remove(source)
                setattr(self, attribute, 0)
        self.queue.clear()
        self.local_dirty = False
        self.remote_pending = False
        self._feedback_followup_pending = False
        self.safety_alert = None
        if self.engine.running:
            self.engine.cancel()
