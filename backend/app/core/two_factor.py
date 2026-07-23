"""TOTP and recovery-code primitives for Mama AI two-factor authentication.

Per-user TOTP secrets are derived from a server-held secret key, a user ID,
and a random per-user salt. The raw TOTP secret is never persisted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote, urlencode


TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SECRET_BYTES = 20
TWO_FACTOR_KEY_MINIMUM_LENGTH = 32
RECOVERY_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
RECOVERY_CODE_GROUPS = 4
RECOVERY_CODE_GROUP_LENGTH = 4


def _validate_server_key(server_key: str) -> bytes:
    if not isinstance(server_key, str):
        raise TypeError("Two-factor secret key must be text.")

    normalized = server_key.strip()

    if len(normalized) < TWO_FACTOR_KEY_MINIMUM_LENGTH:
        raise ValueError(
            "Two-factor secret key must contain at least "
            f"{TWO_FACTOR_KEY_MINIMUM_LENGTH} characters."
        )

    return normalized.encode("utf-8")


def generate_two_factor_salt() -> str:
    """Return a random, non-secret per-user derivation salt."""

    return secrets.token_urlsafe(24)


def derive_totp_secret(
    *,
    server_key: str,
    user_id: str,
    salt: str,
) -> str:
    """Derive one RFC 3548 base32 TOTP secret without storing it."""

    key = _validate_server_key(server_key)

    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("User ID cannot be empty.")

    if not isinstance(salt, str) or len(salt.strip()) < 16:
        raise ValueError("Two-factor salt is invalid.")

    material = hmac.new(
        key,
        (
            "mama-ai:two-factor:v1:"
            + user_id.strip()
            + ":"
            + salt.strip()
        ).encode("utf-8"),
        hashlib.sha256,
    ).digest()[:TOTP_SECRET_BYTES]

    return base64.b32encode(material).decode("ascii").rstrip("=")


def _decode_totp_secret(secret: str) -> bytes:
    if not isinstance(secret, str):
        raise TypeError("TOTP secret must be text.")

    normalized = secret.strip().replace(" ", "").upper()

    if not normalized:
        raise ValueError("TOTP secret cannot be empty.")

    padding = "=" * ((-len(normalized)) % 8)

    try:
        return base64.b32decode(
            (normalized + padding).encode("ascii"),
            casefold=True,
        )
    except Exception as exc:
        raise ValueError("TOTP secret is invalid.") from exc


def _utc_timestamp(value: datetime | None) -> int:
    current = value or datetime.now(timezone.utc)

    if not isinstance(current, datetime):
        raise TypeError("TOTP clock must return datetime.")

    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    return int(current.astimezone(timezone.utc).timestamp())


def generate_totp_code(
    secret: str,
    *,
    at: datetime | None = None,
    counter: int | None = None,
    digits: int = TOTP_DIGITS,
    period_seconds: int = TOTP_PERIOD_SECONDS,
) -> str:
    """Generate one RFC 6238 HMAC-SHA1 TOTP code."""

    if isinstance(digits, bool) or not isinstance(digits, int):
        raise TypeError("TOTP digits must be an integer.")

    if not 6 <= digits <= 8:
        raise ValueError("TOTP digits must be between 6 and 8.")

    if (
        isinstance(period_seconds, bool)
        or not isinstance(period_seconds, int)
        or period_seconds < 15
        or period_seconds > 300
    ):
        raise ValueError("TOTP period must be between 15 and 300 seconds.")

    if counter is None:
        counter = _utc_timestamp(at) // period_seconds

    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        raise ValueError("TOTP counter is invalid.")

    digest = hmac.new(
        _decode_totp_secret(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0]
    value = (truncated & 0x7FFFFFFF) % (10**digits)
    return str(value).zfill(digits)


def verify_totp_code(
    secret: str,
    code: str,
    *,
    at: datetime | None = None,
    window: int = 1,
    last_counter: int | None = None,
    digits: int = TOTP_DIGITS,
    period_seconds: int = TOTP_PERIOD_SECONDS,
) -> int | None:
    """Return the accepted counter, or ``None`` for an invalid/replayed code."""

    if not isinstance(code, str):
        return None

    normalized = code.strip().replace(" ", "")

    if len(normalized) != digits or not normalized.isdigit():
        return None

    if isinstance(window, bool) or not isinstance(window, int):
        raise TypeError("TOTP verification window must be an integer.")

    if not 0 <= window <= 10:
        raise ValueError("TOTP verification window must be between 0 and 10.")

    current_counter = _utc_timestamp(at) // period_seconds

    for candidate in range(
        current_counter - window,
        current_counter + window + 1,
    ):
        if candidate < 0:
            continue

        if last_counter is not None and candidate <= last_counter:
            continue

        expected = generate_totp_code(
            secret,
            counter=candidate,
            digits=digits,
            period_seconds=period_seconds,
        )

        if secrets.compare_digest(normalized, expected):
            return candidate

    return None


def build_otpauth_uri(
    *,
    secret: str,
    account_name: str,
    issuer: str,
) -> str:
    """Build an authenticator-compatible ``otpauth://`` URI."""

    account = str(account_name).strip()
    provider = str(issuer).strip()

    if not account:
        raise ValueError("Two-factor account name cannot be empty.")

    if not provider:
        raise ValueError("Two-factor issuer cannot be empty.")

    label = quote(f"{provider}:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": provider,
            "algorithm": "SHA1",
            "digits": str(TOTP_DIGITS),
            "period": str(TOTP_PERIOD_SECONDS),
        }
    )
    return f"otpauth://totp/{label}?{query}"


def normalize_recovery_code(code: str) -> str:
    if not isinstance(code, str):
        raise TypeError("Recovery code must be text.")

    normalized = "".join(
        character
        for character in code.strip().upper()
        if character not in {"-", " "}
    )

    expected_length = RECOVERY_CODE_GROUPS * RECOVERY_CODE_GROUP_LENGTH

    if len(normalized) != expected_length:
        raise ValueError("Recovery code is invalid.")

    if any(character not in RECOVERY_CODE_ALPHABET for character in normalized):
        raise ValueError("Recovery code is invalid.")

    return normalized


def format_recovery_code(normalized: str) -> str:
    value = normalize_recovery_code(normalized)
    return "-".join(
        value[index : index + RECOVERY_CODE_GROUP_LENGTH]
        for index in range(0, len(value), RECOVERY_CODE_GROUP_LENGTH)
    )


def generate_recovery_codes(count: int) -> list[str]:
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("Recovery-code count must be an integer.")

    if not 5 <= count <= 20:
        raise ValueError("Recovery-code count must be between 5 and 20.")

    codes: set[str] = set()
    expected_length = RECOVERY_CODE_GROUPS * RECOVERY_CODE_GROUP_LENGTH

    while len(codes) < count:
        raw = "".join(
            secrets.choice(RECOVERY_CODE_ALPHABET)
            for _ in range(expected_length)
        )
        codes.add(format_recovery_code(raw))

    return sorted(codes)


def fingerprint_recovery_code(code: str) -> str:
    normalized = normalize_recovery_code(code)
    return hashlib.sha256(
        ("mama-ai:two-factor-recovery:v1:" + normalized).encode("utf-8")
    ).hexdigest()


def fingerprint_two_factor_challenge(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("Two-factor challenge token must be text.")

    normalized = token.strip()

    if len(normalized) < 32 or len(normalized) > 2048:
        raise ValueError("Two-factor challenge token is invalid.")

    return hashlib.sha256(
        ("mama-ai:two-factor-challenge:v1:" + normalized).encode("utf-8")
    ).hexdigest()


def validate_recovery_fingerprints(values: Iterable[str]) -> list[str]:
    normalized = [str(value).strip().lower() for value in values]

    if not 5 <= len(normalized) <= 20:
        raise ValueError("Recovery-code fingerprints must contain 5 to 20 values.")

    if len(set(normalized)) != len(normalized):
        raise ValueError("Recovery-code fingerprints must be unique.")

    for value in normalized:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Recovery-code fingerprint is invalid.")

    return normalized


__all__ = [
    "TOTP_DIGITS",
    "TOTP_PERIOD_SECONDS",
    "TWO_FACTOR_KEY_MINIMUM_LENGTH",
    "build_otpauth_uri",
    "derive_totp_secret",
    "fingerprint_recovery_code",
    "fingerprint_two_factor_challenge",
    "format_recovery_code",
    "generate_recovery_codes",
    "generate_totp_code",
    "generate_two_factor_salt",
    "normalize_recovery_code",
    "validate_recovery_fingerprints",
    "verify_totp_code",
]
