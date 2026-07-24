"""Security primitives for trusted devices and account API keys."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from ipaddress import ip_address
from typing import Final
from uuid import UUID, uuid4


API_KEY_PREFIX: Final[str] = "mamaak1"
API_KEY_SECRET_BYTES: Final[int] = 32
API_KEY_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "api.read",
        "api.write",
        "automation.execute",
    }
)


def normalize_api_key_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("API key name must be text.")

    normalized = " ".join(name.strip().split())

    if not normalized:
        raise ValueError("API key name cannot be empty.")

    if len(normalized) > 100:
        raise ValueError("API key name cannot exceed 100 characters.")

    return normalized


def normalize_api_key_scopes(
    scopes: Iterable[str] | str,
    *,
    require_one: bool = True,
) -> tuple[str, ...]:
    if isinstance(scopes, str):
        values = scopes.split(",")
    else:
        values = list(scopes)

    normalized: set[str] = set()

    for scope in values:
        if not isinstance(scope, str):
            raise TypeError("API key scopes must be text.")

        value = scope.strip().lower()

        if not value:
            continue

        if value not in API_KEY_SCOPES:
            raise ValueError(
                "API key scope must be one of: "
                + ", ".join(sorted(API_KEY_SCOPES))
                + "."
            )

        normalized.add(value)

    if require_one and not normalized:
        raise ValueError("At least one API key scope is required.")

    return tuple(sorted(normalized))


def generate_api_key() -> tuple[str, str]:
    """Return ``(key_id, raw_api_key)`` without persisting the raw key."""

    key_id = uuid4().hex
    secret = secrets.token_urlsafe(API_KEY_SECRET_BYTES)
    return key_id, f"{API_KEY_PREFIX}.{key_id}.{secret}"


def parse_api_key(raw_api_key: str) -> tuple[str, str]:
    if not isinstance(raw_api_key, str):
        raise TypeError("API key must be text.")

    value = raw_api_key.strip()
    parts = value.split(".")

    if len(parts) != 3 or parts[0] != API_KEY_PREFIX:
        raise ValueError("API key format is invalid.")

    key_id = parts[1]
    secret = parts[2]

    try:
        parsed = UUID(hex=key_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("API key format is invalid.") from exc

    if parsed.hex != key_id.lower():
        raise ValueError("API key format is invalid.")

    if len(secret) < 32 or len(secret) > 256:
        raise ValueError("API key format is invalid.")

    return key_id.lower(), value


def fingerprint_api_key(raw_api_key: str) -> str:
    _, normalized = parse_api_key(raw_api_key)
    return hashlib.sha256(
        ("mama-ai:account-api-key:" + normalized).encode("utf-8")
    ).hexdigest()


def api_key_reference(raw_api_key: str) -> str:
    key_id, _ = parse_api_key(raw_api_key)
    return key_id[:12]


def fingerprint_device_reference(client_ref: str) -> str:
    if not isinstance(client_ref, str):
        raise TypeError("Device client reference must be text.")

    normalized = client_ref.strip()

    if not normalized:
        raise ValueError("Device client reference cannot be empty.")

    if len(normalized) > 512:
        raise ValueError(
            "Device client reference cannot exceed 512 characters."
        )

    return hashlib.sha256(
        ("mama-ai:device-reference:" + normalized).encode("utf-8")
    ).hexdigest()


def normalize_device_name(device_name: str | None) -> str:
    if device_name is None:
        return "Unnamed device"

    if not isinstance(device_name, str):
        raise TypeError("Device name must be text.")

    normalized = " ".join(device_name.strip().split())

    if not normalized:
        return "Unnamed device"

    if len(normalized) > 100:
        raise ValueError("Device name cannot exceed 100 characters.")

    return normalized


def normalize_user_agent(user_agent: str | None) -> str | None:
    if user_agent is None:
        return None

    if not isinstance(user_agent, str):
        raise TypeError("User agent must be text.")

    normalized = user_agent.strip()

    if not normalized:
        return None

    if len(normalized) > 512:
        normalized = normalized[:512]

    return normalized


def normalize_ip_address(client_ip: str | None) -> str | None:
    if client_ip is None:
        return None

    if not isinstance(client_ip, str):
        raise TypeError("Client IP address must be text.")

    value = client_ip.strip()

    if not value:
        return None

    try:
        return str(ip_address(value))
    except ValueError as exc:
        raise ValueError("Client IP address is invalid.") from exc


__all__ = [
    "API_KEY_PREFIX",
    "API_KEY_SCOPES",
    "api_key_reference",
    "fingerprint_api_key",
    "fingerprint_device_reference",
    "generate_api_key",
    "normalize_api_key_name",
    "normalize_api_key_scopes",
    "normalize_device_name",
    "normalize_ip_address",
    "normalize_user_agent",
    "parse_api_key",
]
