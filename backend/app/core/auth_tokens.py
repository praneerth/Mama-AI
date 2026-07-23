"""
Compact HMAC-SHA256 access tokens using only Python's standard library.

These tokens are intentionally not advertised as JWTs. Their format is:

    mama1.<base64url-json-payload>.<base64url-signature>

The payload is signed, bounded, short-lived, and contains no password or
refresh-token material.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


TOKEN_PREFIX = "mama1"
TOKEN_ISSUER = "mama-ai"
TOKEN_TYPE = "access"
SIGNING_SECRET_MINIMUM_LENGTH = 32
MAXIMUM_TOKEN_LENGTH = 4096


class AccessTokenError(ValueError):
    """Base class for access-token failures."""


class AccessTokenConfigurationError(
    AccessTokenError
):
    """Signing configuration is missing or unsafe."""


class InvalidAccessTokenError(
    AccessTokenError
):
    """The supplied access token is invalid or expired."""


def _base64url_encode(
    value: bytes,
) -> str:
    return base64.urlsafe_b64encode(
        value
    ).rstrip(b"=").decode("ascii")


def _base64url_decode(
    value: str,
) -> bytes:
    padding = "=" * (
        (-len(value)) % 4
    )

    try:
        return base64.urlsafe_b64decode(
            (value + padding).encode(
                "ascii"
            )
        )

    except Exception as exc:
        raise InvalidAccessTokenError(
            "Access token encoding is invalid."
        ) from exc


def _utc_timestamp(
    value: datetime,
) -> int:
    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return int(
        value.astimezone(
            timezone.utc
        ).timestamp()
    )


class SignedAccessTokenCodec:
    """Issue and verify Mama AI signed access tokens."""

    def __init__(
        self,
        *,
        signing_secret: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(
            signing_secret,
            str,
        ):
            raise TypeError(
                "Access-token signing secret must be text."
            )

        secret = signing_secret.strip()

        if len(
            secret
        ) < SIGNING_SECRET_MINIMUM_LENGTH:
            raise AccessTokenConfigurationError(
                "Access-token signing secret must contain "
                f"at least {SIGNING_SECRET_MINIMUM_LENGTH} characters."
            )

        self._secret = secret.encode(
            "utf-8"
        )
        self._clock = (
            clock
            if clock is not None
            else lambda: datetime.now(
                timezone.utc
            )
        )

    def issue(
        self,
        *,
        user_id: str,
        session_id: str,
        expires_in_seconds: int,
    ) -> str:
        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )
        session_id = self._validate_text(
            session_id,
            "Session ID",
            128,
        )

        if (
            isinstance(
                expires_in_seconds,
                bool,
            )
            or not isinstance(
                expires_in_seconds,
                int,
            )
        ):
            raise TypeError(
                "Access-token expiry must be an integer."
            )

        if not 60 <= expires_in_seconds <= 86400:
            raise ValueError(
                "Access-token expiry must be between "
                "60 and 86400 seconds."
            )

        now = self._now_timestamp()
        payload = {
            "iss": TOKEN_ISSUER,
            "typ": TOKEN_TYPE,
            "sub": user_id,
            "sid": session_id,
            "iat": now,
            "exp": now + expires_in_seconds,
            "jti": uuid4().hex,
        }
        encoded_payload = _base64url_encode(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signing_input = (
            TOKEN_PREFIX
            + "."
            + encoded_payload
        )
        signature = hmac.new(
            self._secret,
            signing_input.encode(
                "ascii"
            ),
            hashlib.sha256,
        ).digest()

        return (
            signing_input
            + "."
            + _base64url_encode(
                signature
            )
        )

    def verify(
        self,
        token: str,
    ) -> dict[str, Any]:
        if not isinstance(token, str):
            raise InvalidAccessTokenError(
                "Access token must be text."
            )

        token = token.strip()

        if (
            not token
            or len(token) > MAXIMUM_TOKEN_LENGTH
        ):
            raise InvalidAccessTokenError(
                "Access token is invalid."
            )

        parts = token.split(".")

        if (
            len(parts) != 3
            or parts[0] != TOKEN_PREFIX
        ):
            raise InvalidAccessTokenError(
                "Access token format is invalid."
            )

        signing_input = (
            parts[0]
            + "."
            + parts[1]
        )
        expected_signature = hmac.new(
            self._secret,
            signing_input.encode(
                "ascii"
            ),
            hashlib.sha256,
        ).digest()
        supplied_signature = (
            _base64url_decode(
                parts[2]
            )
        )

        if not hmac.compare_digest(
            expected_signature,
            supplied_signature,
        ):
            raise InvalidAccessTokenError(
                "Access token signature is invalid."
            )

        try:
            payload = json.loads(
                _base64url_decode(
                    parts[1]
                ).decode("utf-8")
            )

        except (
            UnicodeDecodeError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise InvalidAccessTokenError(
                "Access token payload is invalid."
            ) from exc

        if not isinstance(
            payload,
            Mapping,
        ):
            raise InvalidAccessTokenError(
                "Access token payload is invalid."
            )

        payload = dict(payload)

        if (
            payload.get("iss")
            != TOKEN_ISSUER
            or payload.get("typ")
            != TOKEN_TYPE
        ):
            raise InvalidAccessTokenError(
                "Access token claims are invalid."
            )

        user_id = payload.get("sub")
        session_id = payload.get("sid")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        token_id = payload.get("jti")

        self._validate_text(
            user_id,
            "Access-token user ID",
            128,
        )
        self._validate_text(
            session_id,
            "Access-token session ID",
            128,
        )
        self._validate_text(
            token_id,
            "Access-token ID",
            128,
        )

        if (
            isinstance(issued_at, bool)
            or not isinstance(
                issued_at,
                int,
            )
            or isinstance(
                expires_at,
                bool,
            )
            or not isinstance(
                expires_at,
                int,
            )
        ):
            raise InvalidAccessTokenError(
                "Access token timestamps are invalid."
            )

        now = self._now_timestamp()

        if issued_at > now + 60:
            raise InvalidAccessTokenError(
                "Access token issue time is invalid."
            )

        if expires_at <= now:
            raise InvalidAccessTokenError(
                "Access token has expired."
            )

        if expires_at - issued_at > 86400:
            raise InvalidAccessTokenError(
                "Access token lifetime is invalid."
            )

        return payload

    def _now_timestamp(self) -> int:
        current = self._clock()

        if not isinstance(
            current,
            datetime,
        ):
            raise TypeError(
                "Access-token clock must return datetime."
            )

        return _utc_timestamp(
            current
        )

    @staticmethod
    def _validate_text(
        value: Any,
        field_name: str,
        maximum_length: int,
    ) -> str:
        if not isinstance(value, str):
            raise InvalidAccessTokenError(
                f"{field_name} must be text."
            )

        value = value.strip()

        if (
            not value
            or len(value) > maximum_length
        ):
            raise InvalidAccessTokenError(
                f"{field_name} is invalid."
            )

        return value


__all__ = [
    "AccessTokenConfigurationError",
    "AccessTokenError",
    "InvalidAccessTokenError",
    "SignedAccessTokenCodec",
    "TOKEN_ISSUER",
    "TOKEN_PREFIX",
    "TOKEN_TYPE",
]
