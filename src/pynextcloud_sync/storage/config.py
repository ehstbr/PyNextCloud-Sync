from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from pynextcloud_sync.core.exclusions import DEFAULT_PATTERNS, validate_pattern
from pynextcloud_sync.util.paths import config_dir, default_sync_root, ensure_private_directory


SCHEMA_VERSION = 2

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "account": None,
    "sync": {
        "local_inotify_enabled": True,
        "local_interval_enabled": False,
        "local_interval_minutes": 5,
        "remote_push_enabled": True,
        "remote_interval_enabled": True,
        "remote_interval_minutes": 10,
        "max_sync_retries": 3,
        "detailed_output": True,
        "exclude_patterns_enabled": True,
        "exclude_patterns": list(DEFAULT_PATTERNS),
    },
    "general": {"autostart": True, "pause_on_battery": False},
    "logging": {"save_logs": True, "retention_days": 30},
    "network": {"custom_proxy": None, "trust_invalid_certificates": False},
    "safety": {
        "bootstrap_complete": False,
        "bootstrap_completed_at": None,
        "guard_enabled": True,
        "deletion_count_threshold": 10,
        "deletion_percent_threshold": 20,
    },
    "runtime": {
        "last_successful_sync": None,
        "last_exit_code": None,
        "account_details": None,
        "server_details": None,
    },
}


class ConfigurationError(ValueError):
    pass


def normalize_server_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("Enter a complete HTTP or HTTPS Nextcloud URL.")
    if parsed.username or parsed.password:
        raise ConfigurationError("Credentials must not be included in the server URL.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def _deep_merge(defaults: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(defaults)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_config(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigurationError("Configuration root must be an object.")
    version = data.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ConfigurationError(
            f"Configuration schema {version} is newer than this application supports."
        )
    merged = _deep_merge(DEFAULT_CONFIG, data)
    merged["schema_version"] = SCHEMA_VERSION

    account = merged.get("account")
    if account is not None:
        if not isinstance(account, dict):
            raise ConfigurationError("Account configuration is invalid.")
        account["server_url"] = normalize_server_url(str(account.get("server_url", "")))
        if not str(account.get("login_name", "")).strip():
            raise ConfigurationError("Account username is missing.")
        root = Path(str(account.get("local_root", default_sync_root()))).expanduser()
        if not root.is_absolute():
            raise ConfigurationError("The local synchronization folder must be absolute.")
        account["local_root"] = str(root)
        authorization = account.get("authorization_name")
        if authorization is not None:
            authorization = str(authorization).strip()
            account["authorization_name"] = authorization or None

    sync = merged["sync"]
    for key, lower, upper in (
        ("local_interval_minutes", 1, 1440),
        ("remote_interval_minutes", 1, 1440),
        ("max_sync_retries", 1, 10),
    ):
        try:
            value = int(sync[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"Invalid setting: {key}") from exc
        if not lower <= value <= upper:
            raise ConfigurationError(f"{key} must be between {lower} and {upper}.")
        sync[key] = value
    logging_config = merged["logging"]
    try:
        retention_days = int(logging_config["retention_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError("Invalid setting: retention_days") from exc
    if not 1 <= retention_days <= 365:
        raise ConfigurationError("retention_days must be between 1 and 365.")
    logging_config["retention_days"] = retention_days
    logging_config["save_logs"] = bool(logging_config.get("save_logs", True))
    safety = merged["safety"]
    safety["bootstrap_complete"] = bool(safety.get("bootstrap_complete", False))
    safety["guard_enabled"] = bool(safety.get("guard_enabled", True))
    try:
        deletion_count = int(safety.get("deletion_count_threshold", 10))
        deletion_percent = int(safety.get("deletion_percent_threshold", 20))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Invalid safety deletion threshold.") from exc
    if not 1 <= deletion_count <= 100_000:
        raise ConfigurationError("deletion_count_threshold must be between 1 and 100000.")
    if not 1 <= deletion_percent <= 100:
        raise ConfigurationError("deletion_percent_threshold must be between 1 and 100.")
    safety["deletion_count_threshold"] = deletion_count
    safety["deletion_percent_threshold"] = deletion_percent
    sync["exclude_patterns"] = [
        validate_pattern(str(pattern)) for pattern in sync.get("exclude_patterns", [])
    ]
    proxy = merged["network"].get("custom_proxy")
    if proxy:
        parsed_proxy = urlsplit(str(proxy))
        if (
            parsed_proxy.scheme.lower() not in {"http", "https"}
            or not parsed_proxy.netloc
            or parsed_proxy.username
            or parsed_proxy.password
        ):
            raise ConfigurationError(
                "The custom proxy must be an HTTP(S) URL without embedded credentials."
            )
    return merged


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    @property
    def configured(self) -> bool:
        return self.data.get("account") is not None

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.data = copy.deepcopy(DEFAULT_CONFIG)
            return self.data
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = validate_config(parsed)
        except (OSError, json.JSONDecodeError, ConfigurationError) as exc:
            raise ConfigurationError(f"Could not load {self.path}: {exc}") from exc
        return self.data

    def save(self, *, notify: bool = True) -> None:
        self.data = validate_config(self.data)
        ensure_private_directory(self.path.parent)
        temporary = self.path.with_suffix(".tmp")
        payload = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        if notify:
            for listener in tuple(self._listeners):
                listener(self.data)

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def reset_account(self) -> None:
        runtime = copy.deepcopy(self.data.get("runtime", DEFAULT_CONFIG["runtime"]))
        runtime["account_details"] = None
        runtime["server_details"] = None
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.data["runtime"] = runtime
        self.save()
