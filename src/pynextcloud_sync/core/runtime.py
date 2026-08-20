from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from gi.repository import GLib

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.inotify import InotifyOverflowError, InotifyWatcher
from pynextcloud_sync.core.network import NetworkWatcher
from pynextcloud_sync.core.power import PowerWatcher
from pynextcloud_sync.core.scheduler import SyncScheduler
from pynextcloud_sync.core.state import AppState, PushState, StateController
from pynextcloud_sync.core.suspend import SuspendWatcher
from pynextcloud_sync.core.sync_engine import SyncEngine, SyncResult
from pynextcloud_sync.core.safety import SafetyAlert
from pynextcloud_sync.core.timers import SyncTimers
from pynextcloud_sync.core.triggers import Trigger
from pynextcloud_sync.nextcloud.details_refresher import RemoteDetailsRefresher
from pynextcloud_sync.nextcloud.models import AccountDetails, ServerDetails
from pynextcloud_sync.nextcloud.push import NotifyPushClient
from pynextcloud_sync.util.i18n import _


class RuntimeController:
    def __init__(
        self,
        config: Any,
        credentials: Any,
        logger: Any,
        notify_failure: Callable[[SyncResult], None] | None = None,
        notify_safety_alert: Callable[[SafetyAlert], None] | None = None,
        account_details_updated: Callable[[AccountDetails], None] | None = None,
        server_details_updated: Callable[[ServerDetails], None] | None = None,
        storage_usage_updated: Callable[[int | None, int | None], None] | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.logger = logger
        self.notify_failure = notify_failure
        self.details_refresher = RemoteDetailsRefresher(
            config,
            credentials,
            logger,
            account_details_updated,
            server_details_updated,
            storage_usage_updated,
        )
        self.state = StateController(
            AppState.IDLE_OK if config.configured else AppState.UNCONFIGURED
        )
        self.push_state = PushState.DISABLED
        self.push_message = ""
        self.engine = SyncEngine(logger)
        self.scheduler = SyncScheduler(
            config,
            credentials,
            self.engine,
            self.state,
            logger,
            self._sync_completed,
            notify_safety_alert,
        )
        self.timers = SyncTimers(self.scheduler.request)
        self.network = NetworkWatcher(self._network_changed)
        self.power = PowerWatcher(self._power_changed, logger)
        self.suspend = SuspendWatcher(self._resumed, logger)
        self.push = NotifyPushClient(
            lambda: self.scheduler.request(Trigger.REMOTE_PUSH), self._push_changed, logger
        )
        self.inotify: InotifyWatcher | None = None
        self._fallback_source = 0
        self._inotify_recovery_source = 0
        self._started = False
        self._error_notified = False
        self._timers_signature: tuple[object, ...] | None = None
        self._inotify_signature: tuple[object, ...] | None = None
        self._push_signature: tuple[object, ...] | None = None
        self._unsubscribe = self.config.subscribe(lambda _data: self.reconfigure())

    @property
    def watched_directories(self) -> int:
        return self.inotify.watch_count if self.inotify else 0

    def start(self) -> None:
        if self._started or not self.config.configured:
            return
        self._started = True
        self.network.start()
        self.power.start()
        self.suspend.start()
        self.reconfigure()
        self.scheduler._set_idle_state()
        self.details_refresher.start()
        if not self.scheduler.manual_only:
            self.scheduler.request(Trigger.STARTUP)

    def stop(self) -> None:
        self._started = False
        self.timers.stop()
        self.network.stop()
        self.power.stop()
        self.suspend.stop()
        self.push.disconnect()
        self.details_refresher.stop()
        self.scheduler.stop()
        if self.inotify:
            self.inotify.stop()
            self.inotify = None
        if self._fallback_source:
            GLib.source_remove(self._fallback_source)
            self._fallback_source = 0
        if self._inotify_recovery_source:
            GLib.source_remove(self._inotify_recovery_source)
            self._inotify_recovery_source = 0
        self._timers_signature = None
        self._inotify_signature = None
        self._push_signature = None
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def reconfigure(self) -> None:
        if not self._started or not self.config.configured:
            return
        sync = self.config.data["sync"]
        account = self.config.data["account"]
        timer_signature = (
            bool(sync.get("local_interval_enabled", False)),
            int(sync.get("local_interval_minutes", 5)),
            bool(sync.get("remote_interval_enabled", True)),
            int(sync.get("remote_interval_minutes", 10)),
        )
        if timer_signature != self._timers_signature:
            self._timers_signature = timer_signature
            self.timers.configure(sync)

        inotify_signature = (
            bool(sync.get("local_inotify_enabled", True)),
            account["local_root"],
            bool(sync.get("exclude_patterns_enabled", True)),
            tuple(sync.get("exclude_patterns", [])),
        )
        if inotify_signature != self._inotify_signature:
            self._inotify_signature = inotify_signature
            self._configure_inotify(sync)

        push_signature = (
            bool(sync.get("remote_push_enabled", True)),
            account["server_url"],
            account["login_name"],
            bool(self.config.data["network"].get("trust_invalid_certificates", False)),
        )
        if push_signature != self._push_signature:
            reconnect = self._push_signature is not None
            self._push_signature = push_signature
            if reconnect:
                self.push.disconnect(keep_enabled=True)
            self._configure_push(sync, push_signature)
        if self.power.available:
            self._power_changed(self.power.on_battery)
        self.scheduler._set_idle_state()

    def _configure_inotify(self, sync: dict) -> None:
        if self._fallback_source:
            GLib.source_remove(self._fallback_source)
            self._fallback_source = 0
        if self.inotify:
            self.inotify.stop()
            self.inotify = None
        if not sync.get("local_inotify_enabled", True):
            return
        account = self.config.data["account"]
        matcher = ExclusionMatcher(
            sync.get("exclude_patterns", []), sync.get("exclude_patterns_enabled", True)
        )
        watcher = InotifyWatcher(
            Path(account["local_root"]),
            matcher,
            lambda _path: self.scheduler.request(Trigger.LOCAL_INOTIFY),
            self._inotify_degraded,
            self.logger,
        )
        try:
            watcher.start()
            self.inotify = watcher
        except Exception as exc:
            self._inotify_degraded(exc)

    def _inotify_degraded(self, error: Exception) -> None:
        self.logger.warning("Filesystem monitoring is degraded: %s", error)
        if self.inotify:
            self.inotify.stop()
            self.inotify = None
        if isinstance(error, InotifyOverflowError):
            # Overflow means events were lost, not that synchronization failed.
            # Rebuild the watcher, then let nextcloudcmd perform one normal full
            # reconciliation after the existing safety checks pass.
            self.state.set(AppState.SYNC_QUEUED, _("Synchronization scheduled"))
            if not self._inotify_recovery_source:
                self._inotify_recovery_source = GLib.idle_add(self._recover_inotify_overflow)
            return
        if not self.config.data["sync"].get("local_interval_enabled", False) and not self._fallback_source:
            minutes = int(self.config.data["sync"].get("local_interval_minutes", 5))
            self._fallback_source = GLib.timeout_add_seconds(
                minutes * 60, self._fallback_local_interval
            )
        self.state.set(
            AppState.ERROR,
            _("Filesystem watch limit reached; using a local safety interval for this session"),
        )

    def _recover_inotify_overflow(self) -> bool:
        self._inotify_recovery_source = 0
        if not self._started or not self.config.configured:
            return GLib.SOURCE_REMOVE
        sync = self.config.data["sync"]
        if sync.get("local_inotify_enabled", True):
            self._configure_inotify(sync)
        self.logger.info(
            "inotify overflow recovery requested a protected reconciliation through nextcloudcmd."
        )
        self.scheduler.request(Trigger.LOCAL_RECOVERY)
        return GLib.SOURCE_REMOVE

    def _fallback_local_interval(self) -> bool:
        self.scheduler.request(Trigger.LOCAL_INTERVAL)
        return GLib.SOURCE_CONTINUE

    def _configure_push(
        self, sync: dict, signature: tuple[object, ...] | None = None
    ) -> None:
        account = self.config.data["account"]
        enabled = bool(sync.get("remote_push_enabled", True))
        self.push.http.trust_invalid_certificates = bool(
            self.config.data["network"].get("trust_invalid_certificates", False)
        )
        if not enabled:
            self.push.configure(account["server_url"], account["login_name"], "", False)
            return

        def secret_ready(password: str | None, error: Exception | None) -> None:
            if not self._started or (
                signature is not None and signature != self._push_signature
            ):
                return
            if error or not password:
                self.push_state = PushState.AUTH_REQUIRED
                self.push_message = _("Unlock the password keyring to connect push notifications.")
                return
            self.logger.add_secret(password)
            self.push.configure(
                account["server_url"], account["login_name"], password, enabled
            )

        self.credentials.lookup(account["server_url"], account["login_name"], secret_ready)

    def _network_changed(self, online: bool) -> None:
        self.scheduler.set_online(online)
        self.push.set_online(online)

    def _power_changed(self, on_battery: bool) -> None:
        pause = bool(self.config.data["general"].get("pause_on_battery", False)) and on_battery
        self.scheduler.set_battery_paused(pause)

    def _resumed(self) -> None:
        self.push.disconnect(keep_enabled=True)
        if self.config.data["sync"].get("remote_push_enabled", True):
            self._push_signature = None
            self.reconfigure()
        if not self.scheduler.manual_only or self.scheduler.queue:
            self.scheduler.request(Trigger.RESUME)

    def _push_changed(self, state: PushState, message: str) -> None:
        self.push_state = state
        self.push_message = message
        self.logger.info("notify_push state: %s (%s)", state.value, message)
        sync = self.config.data["sync"]
        if (
            sync.get("remote_push_enabled", True)
            and not sync.get("remote_interval_enabled", True)
            and state in {PushState.UNSUPPORTED, PushState.RECONNECTING, PushState.AUTH_REQUIRED}
            and self.state.snapshot.state in {AppState.IDLE_OK, AppState.IDLE_MANUAL_ONLY}
        ):
            self.state.set(
                AppState.IDLE_OK,
                _("Automatic remote detection is unavailable; use Sync Now or enable the remote safety interval."),
            )

    def _sync_completed(self, result: SyncResult) -> None:
        if result.successful:
            self._error_notified = False
            self.details_refresher.refresh_account(storage_only=True)
        elif self.notify_failure and not self._error_notified:
            self._error_notified = True
            self.notify_failure(result)

    def sync_now(self) -> None:
        unlock_attempt = self.scheduler.keyring_locked
        self.scheduler.request(Trigger.MANUAL)
        if unlock_attempt and self.config.data["sync"].get("remote_push_enabled", True):
            self._configure_push(
                self.config.data["sync"],
                self._push_signature,
            )

    def authentication_restored(self) -> None:
        self.scheduler.authentication_restored()
        self.push.disconnect(keep_enabled=True)
        self._push_signature = None
        self.reconfigure()
        self.scheduler.request(Trigger.MANUAL)

    def authentication_rejected(self) -> None:
        self.scheduler.authentication_rejected()

    def set_paused(self, paused: bool) -> None:
        self.scheduler.set_user_paused(paused)

    def approve_safety_once(self) -> None:
        self.scheduler.approve_safety_once()
