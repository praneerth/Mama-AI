import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from app.core.auth_tokens import (
    AccessTokenConfigurationError,
    InvalidAccessTokenError,
    SignedAccessTokenCodec,
)


class MutableClock:

    def __init__(
        self,
        current: datetime,
    ) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(
        self,
        *,
        seconds: int,
    ) -> None:
        self.current += timedelta(
            seconds=seconds
        )


class TestSignedAccessTokenCodec(
    unittest.TestCase
):

    SECRET = (
        "mama-auth-signing-secret-"
        + ("s" * 48)
    )

    def setUp(self) -> None:
        self.clock = MutableClock(
            datetime(
                2026,
                7,
                23,
                10,
                0,
                tzinfo=timezone.utc,
            )
        )
        self.codec = SignedAccessTokenCodec(
            signing_secret=self.SECRET,
            clock=self.clock,
        )

    def issue(self) -> str:
        return self.codec.issue(
            user_id="user-1",
            session_id="session-1",
            expires_in_seconds=900,
        )

    def test_issue_and_verify(
        self,
    ) -> None:
        claims = self.codec.verify(
            self.issue()
        )

        self.assertEqual(
            claims["sub"],
            "user-1",
        )
        self.assertEqual(
            claims["sid"],
            "session-1",
        )

    def test_tampered_token_is_rejected(
        self,
    ) -> None:
        token = self.issue()
        tampered = (
            token[:-1]
            + (
                "a"
                if token[-1] != "a"
                else "b"
            )
        )

        with self.assertRaises(
            InvalidAccessTokenError
        ):
            self.codec.verify(
                tampered
            )

    def test_expired_token_is_rejected(
        self,
    ) -> None:
        token = self.issue()
        self.clock.advance(
            seconds=901
        )

        with self.assertRaises(
            InvalidAccessTokenError
        ):
            self.codec.verify(
                token
            )

    def test_wrong_secret_is_rejected(
        self,
    ) -> None:
        token = self.issue()
        other = SignedAccessTokenCodec(
            signing_secret=(
                "other-signing-secret-"
                + ("o" * 48)
            ),
            clock=self.clock,
        )

        with self.assertRaises(
            InvalidAccessTokenError
        ):
            other.verify(token)

    def test_malformed_token_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            InvalidAccessTokenError
        ):
            self.codec.verify(
                "not-a-token"
            )

    def test_short_secret_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            AccessTokenConfigurationError
        ):
            SignedAccessTokenCodec(
                signing_secret="short"
            )

    def test_secret_is_not_embedded(
        self,
    ) -> None:
        self.assertNotIn(
            self.SECRET,
            self.issue(),
        )

    def test_invalid_expiry_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.codec.issue(
                user_id="user-1",
                session_id="session-1",
                expires_in_seconds=30,
            )


if __name__ == "__main__":
    unittest.main()
