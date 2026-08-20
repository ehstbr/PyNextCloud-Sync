from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerDetails:
    product_name: str
    version: str
    maintenance: bool
    needs_database_upgrade: bool


@dataclass(frozen=True)
class AccountDetails:
    display_name: str
    email: str
    quota_used: int | None
    quota_total: int | None
