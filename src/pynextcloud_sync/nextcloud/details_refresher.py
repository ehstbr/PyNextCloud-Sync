from __future__ import annotations

from typing import Any, Callable

from .api import NextcloudApi, NextcloudRateLimitError
from .models import AccountDetails, ServerDetails


class RemoteDetailsRefresher:
    def __init__(
        self,
        config: Any,
        credentials: Any,
        logger: Any,
        account_updated: Callable[[AccountDetails], None] | None = None,
        server_updated: Callable[[ServerDetails], None] | None = None,
        storage_updated: Callable[[int | None, int | None], None] | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.logger = logger
        self.account_updated = account_updated
        self.server_updated = server_updated
        self.storage_updated = storage_updated
        self.api = NextcloudApi()
        self._active = False
        self._account_generation = 0
        self._server_generation = 0

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self.refresh_account()
        self.refresh_server()

    def stop(self) -> None:
        self._active = False
        self._account_generation += 1
        self._server_generation += 1

    def refresh_account(self, *, storage_only: bool = False) -> None:
        if not self._active or not self.config.configured:
            return
        self._account_generation += 1
        generation = self._account_generation
        account = dict(self.config.data["account"])
        identity = (account["server_url"], account["login_name"])
        self._configure_http()

        def account_ready(
            details: AccountDetails | None, error: Exception | None
        ) -> None:
            current = self.config.data.get("account")
            if (
                not self._active
                or generation != self._account_generation
                or not current
                or (current["server_url"], current["login_name"]) != identity
            ):
                return
            if error or not details:
                if isinstance(error, NextcloudRateLimitError):
                    self.logger.info(
                        "Nextcloud limited the account details refresh; "
                        "the last saved details remain available."
                    )
                else:
                    self.logger.warning(
                        "Could not refresh account details: %s",
                        error or "no details returned",
                    )
                return
            if storage_only and self.storage_updated:
                self.storage_updated(details.quota_used, details.quota_total)
            elif self.account_updated:
                self.account_updated(details)

        def credential_ready(
            password: str | None, error: Exception | None
        ) -> None:
            if not self._active or generation != self._account_generation:
                return
            if error or not password:
                self.logger.warning(
                    "Could not refresh account details: %s",
                    error or "stored credential unavailable",
                )
                return
            self.logger.add_secret(password)
            self.api.get_account_details(
                account["server_url"],
                account["login_name"],
                password,
                account_ready,
            )

        self.credentials.lookup(
            account["server_url"], account["login_name"], credential_ready
        )

    def refresh_server(self) -> None:
        if not self._active or not self.config.configured:
            return
        self._server_generation += 1
        generation = self._server_generation
        server_url = self.config.data["account"]["server_url"]
        self._configure_http()

        def server_ready(
            details: ServerDetails | None, error: Exception | None
        ) -> None:
            current = self.config.data.get("account")
            if (
                not self._active
                or generation != self._server_generation
                or not current
                or current["server_url"] != server_url
            ):
                return
            if error or not details:
                self.logger.warning(
                    "Could not refresh server details at startup: %s",
                    error or "no details returned",
                )
                return
            if self.server_updated:
                self.server_updated(details)

        self.api.get_server_details(server_url, server_ready)

    def _configure_http(self) -> None:
        self.api.http.trust_invalid_certificates = bool(
            self.config.data.get("network", {}).get(
                "trust_invalid_certificates", False
            )
        )
