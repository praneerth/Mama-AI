import tempfile
import unittest
from pathlib import Path

from app.core.auth_service import (
    AuthenticationService,
    InvalidCurrentPasswordError,
    SessionNotFoundError,
)
from app.database.auth_db import (
    SQLiteAuthenticationStore,
)


class TestAuthenticationSessionManagementService(
    unittest.TestCase
):

    PASSWORD = (
        "Mama-AI-Strong-Password-2026"
    )
    NEW_PASSWORD = (
        "Mama-AI-New-Strong-Password-2026"
    )
    SECRET = (
        "mama-session-service-secret-"
        + ("s" * 48)
    )

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.store = (
            SQLiteAuthenticationStore(
                Path(
                    self.temp_directory.name
                )
                / "service.db"
            )
        )
        self.service = AuthenticationService(
            store=self.store,
            signing_secret=self.SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
        )
        self.first_user = self.service.register(
            email="first@example.com",
            password=self.PASSWORD,
        )
        self.second_user = self.service.register(
            email="second@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def login(
        self,
        email: str,
    ) -> dict:
        return self.service.login(
            email=email,
            password=self.PASSWORD,
            device_name="Windows",
        )

    def test_list_sessions(
        self,
    ) -> None:
        self.login("first@example.com")

        sessions = self.service.list_sessions(
            user_id=self.first_user[
                "user_id"
            ]
        )

        self.assertEqual(
            len(sessions),
            1,
        )

    def test_revoke_owned_session(
        self,
    ) -> None:
        login = self.login(
            "first@example.com"
        )

        session = self.service.revoke_user_session(
            user_id=self.first_user[
                "user_id"
            ],
            session_id=login["session"][
                "session_id"
            ],
        )

        self.assertEqual(
            session["status"],
            "revoked",
        )

    def test_other_session_is_not_found(
        self,
    ) -> None:
        other = self.login(
            "second@example.com"
        )

        with self.assertRaises(
            SessionNotFoundError
        ):
            self.service.revoke_user_session(
                user_id=self.first_user[
                    "user_id"
                ],
                session_id=other["session"][
                    "session_id"
                ],
            )

    def test_logout_all(
        self,
    ) -> None:
        self.login("first@example.com")
        self.login("first@example.com")

        revoked = self.service.logout_all(
            user_id=self.first_user[
                "user_id"
            ]
        )

        self.assertEqual(
            revoked,
            2,
        )

    def test_change_password(
        self,
    ) -> None:
        login = self.login(
            "first@example.com"
        )

        result = self.service.change_password(
            user_id=self.first_user[
                "user_id"
            ],
            current_password=self.PASSWORD,
            new_password=self.NEW_PASSWORD,
        )

        self.assertEqual(
            result["revoked_sessions"],
            1,
        )
        self.assertEqual(
            self.store.get_session(
                login["session"][
                    "session_id"
                ]
            )["status"],
            "revoked",
        )
        self.assertTrue(
            self.store.verify_user_password(
                email="first@example.com",
                password=self.NEW_PASSWORD,
            )
        )

    def test_invalid_current_password(
        self,
    ) -> None:
        with self.assertRaises(
            InvalidCurrentPasswordError
        ):
            self.service.change_password(
                user_id=self.first_user[
                    "user_id"
                ],
                current_password=(
                    "Wrong-current-password"
                ),
                new_password=self.NEW_PASSWORD,
            )


if __name__ == "__main__":
    unittest.main()
