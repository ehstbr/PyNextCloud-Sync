from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from pynextcloud_sync.nextcloud.models import AccountDetails, ServerDetails


@dataclass(frozen=True)
class CachedStorageUsage:
    used: int | None
    total: int | None


def cached_account_details(config: Any) -> AccountDetails | None:
    payload = config.data.get("runtime", {}).get("account_details")
    if not isinstance(payload, dict) or not payload.get("account_updated_at"):
        return None
    try:
        return AccountDetails(
            display_name=str(payload.get("display_name") or ""),
            email=str(payload.get("email") or ""),
            quota_used=_optional_integer(payload.get("quota_used")),
            quota_total=_optional_integer(payload.get("quota_total")),
        )
    except (TypeError, ValueError):
        return None


def cached_storage_usage(config: Any) -> CachedStorageUsage | None:
    payload = config.data.get("runtime", {}).get("account_details")
    if not isinstance(payload, dict) or not payload.get("storage_updated_at"):
        return None
    try:
        return CachedStorageUsage(
            used=_optional_integer(payload.get("quota_used")),
            total=_optional_integer(payload.get("quota_total")),
        )
    except (TypeError, ValueError):
        return None


def cached_server_details(config: Any) -> ServerDetails | None:
    payload = config.data.get("runtime", {}).get("server_details")
    if not isinstance(payload, dict) or not payload.get("updated_at"):
        return None
    try:
        return ServerDetails(
            product_name=str(payload.get("product_name") or "Nextcloud"),
            version=str(payload.get("version") or ""),
            maintenance=bool(payload.get("maintenance", False)),
            needs_database_upgrade=bool(
                payload.get("needs_database_upgrade", False)
            ),
        )
    except (TypeError, ValueError):
        return None


def store_account_details(config: Any, details: AccountDetails) -> None:
    now = _now()
    config.data["runtime"]["account_details"] = {
        "display_name": details.display_name,
        "email": details.email,
        "quota_used": details.quota_used,
        "quota_total": details.quota_total,
        "account_updated_at": now,
        "storage_updated_at": now,
    }
    config.save(notify=False)


def store_storage_usage(
    config: Any, used: int | None, total: int | None
) -> None:
    existing = config.data["runtime"].get("account_details")
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload["quota_used"] = used
    payload["quota_total"] = total
    payload["storage_updated_at"] = _now()
    config.data["runtime"]["account_details"] = payload
    config.save(notify=False)


def store_server_details(config: Any, details: ServerDetails) -> None:
    config.data["runtime"]["server_details"] = {
        "product_name": details.product_name,
        "version": details.version,
        "maintenance": details.maintenance,
        "needs_database_upgrade": details.needs_database_upgrade,
        "updated_at": _now(),
    }
    config.save(notify=False)


def clear_remote_details(config: Any) -> None:
    config.data["runtime"]["account_details"] = None
    config.data["runtime"]["server_details"] = None


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
