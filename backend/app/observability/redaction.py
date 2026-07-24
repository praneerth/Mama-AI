"""Sensitive-value redaction used by Mama AI observability."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "cookie",
    "credential",
    "private_key",
    "refresh",
    "recovery_code",
)

_BEARER_PATTERN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
)

_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)(password|token|secret|api[_-]?key|code)=([^&\s]+)"
)

_VERSIONED_TOKEN_PATTERN = re.compile(
    r"\b(?:mama1|mak1)\.[A-Za-z0-9._~-]{8,}\b"
)


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Remove common credential forms from free-form text."""

    value = _BEARER_PATTERN.sub("Bearer " + REDACTED, value)
    value = _VERSIONED_TOKEN_PATTERN.sub(REDACTED, value)
    value = _QUERY_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED}",
        value,
    )
    return value


def redact_value(value: Any, *, key: object | None = None) -> Any:
    """Recursively sanitize values before logging or diagnostics."""

    if key is not None and is_sensitive_key(key):
        return REDACTED

    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [redact_value(item) for item in value]

    if isinstance(value, (bytes, bytearray)):
        return f"<{type(value).__name__}:{len(value)}>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return redact_text(str(value))


__all__ = [
    "REDACTED",
    "is_sensitive_key",
    "redact_text",
    "redact_value",
]
