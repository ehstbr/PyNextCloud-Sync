from __future__ import annotations

import re
from collections.abc import Iterable


REDACTED = "[REDACTED]"


class Redactor:
    """Centralized secret removal for logs and diagnostic text."""

    _userinfo = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)
    _query_secret = re.compile(
        r"([?&](?:token|password|appPassword|access_token)=)([^&\s]+)", re.IGNORECASE
    )
    _authorization = re.compile(r"(Authorization:\s*(?:Basic|Bearer)\s+)[^\s]+", re.IGNORECASE)

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: set[str] = {value for value in secrets if value}

    def add_secret(self, secret: str | None) -> None:
        if secret:
            self._secrets.add(secret)

    def redact(self, value: object) -> str:
        text = str(value)
        text = self._userinfo.sub(r"\1" + REDACTED + "@", text)
        text = self._query_secret.sub(r"\1" + REDACTED, text)
        text = self._authorization.sub(r"\1" + REDACTED, text)
        for secret in sorted(self._secrets, key=len, reverse=True):
            if len(secret) >= 3:
                text = text.replace(secret, REDACTED)
        return text
