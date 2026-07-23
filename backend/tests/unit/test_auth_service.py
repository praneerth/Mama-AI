import tempfile
import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

from app.core.auth_service import (
    AccountExistsError,
    AuthenticationConfigurationError,
    AuthenticationService,
    InvalidAccountAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.database.auth_db import (
    SQLiteAuthenticationStore,
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


class TestAuthenticationService(
    unittest.TestCase
):

    PASSWORD = (
        "Mama-AI-Strong-Password-2026"
    )
    SECRET = (
        "mama-auth-service-secret-"
        + ("x" * 48)
    )

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
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
        self.store = (
            SQLiteAuthenticationStore(
                Path(
                    self.temp_directory.name
                )
                / "auth-service.db",
                clock=self.clock,
            )
        )
        self.service = (
            AuthenticationService(
                store=self.store,
                signing_secret=self.SECRET,
                access_token_seconds=900,
                refresh_token_seconds=3600,
                clock=self.clock,
            )
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def register(self) -> dict:
        return self.service.register(
            email="praneeth@example.com",
            password=self.PASSWORD,
            display_name="Praneeth",
        )

    def login(self) -> dict:
        return self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
            device_name="Windows",
        )

    def test_register_account(
        self,
    ) -> None:
        user = self.register()

        self.assertEqual(
            user["status"],
            "active",
        )

    def test_duplicate_registration(
        self,
    ) -> None:
        self.register()

        with self.assertRaises(
            AccountExistsError
        ):
            self.register()

    def test_login_issues_tokens(
        self,
    ) -> None:
        self.register()
        result = self.login()

        self.assertEqual(
            result["token_type"],
            "bearer",
        )
        self.assertTrue(
            result["access_token"]
        )
        self.assertTrue(
            result["refresh_token"]
        )

    def test_invalid_password(
        self,
    ) -> None:
        self.register()

        with self.assertRaises(
            InvalidCredentialsError
        ):
            self.service.login(
                email=(
                    "praneeth@example.com"
                ),
                password=(
                    "Wrong-password-value"
                ),
            )

    def test_disabled_account_cannot_login(
        self,
    ) -> None:
        user = self.register()
        self.store.set_user_status(
            user_id=user["user_id"],
            status="disabled",
        )

        with self.assertRaises(
            InvalidCredentialsError
        ):
            self.login()

    def test_access_token_authentication(
        self,
    ) -> None:
        user = self.register()
        result = self.login()

        authenticated = (
            self.service.authenticate_access_token(
                result["access_token"]
            )
        )

        self.assertEqual(
            authenticated["user"][
                "user_id"
            ],
            user["user_id"],
        )

    def test_refresh_rotates_token(
        self,
    ) -> None:
        self.register()
        first = self.login()
        second = self.service.refresh(
            refresh_token=(
                first["refresh_token"]
            )
        )

        self.assertNotEqual(
            first["refresh_token"],
            second["refresh_token"],
        )

        with self.assertRaises(
            InvalidRefreshTokenError
        ):
            self.service.refresh(
                refresh_token=(
                    first["refresh_token"]
                )
            )

    def test_logout_revokes_access(
        self,
    ) -> None:
        self.register()
        result = self.login()

        self.service.logout(
            session_id=(
                result["session"][
                    "session_id"
                ]
            )
        )

        with self.assertRaises(
            InvalidAccountAccessTokenError
        ):
            self.service.authenticate_access_token(
                result["access_token"]
            )

    def test_expired_access_token(
        self,
    ) -> None:
        self.register()
        result = self.login()
        self.clock.advance(
            seconds=901
        )

        with self.assertRaises(
            InvalidAccountAccessTokenError
        ):
            self.service.authenticate_access_token(
                result["access_token"]
            )

    def test_missing_signing_secret(
        self,
    ) -> None:
        self.register()
        service = AuthenticationService(
            store=self.store,
            signing_secret="",
            access_token_seconds=900,
            refresh_token_seconds=3600,
            clock=self.clock,
        )

        with self.assertRaises(
            AuthenticationConfigurationError
        ):
            service.login(
                email=(
                    "praneeth@example.com"
                ),
                password=self.PASSWORD,
            )


if __name__ == "__main__":
    unittest.main()
