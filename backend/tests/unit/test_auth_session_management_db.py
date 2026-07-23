import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.auth_db import (
    SESSION_TABLE,
    SQLiteAuthenticationStore,
)


class TestAuthenticationSessionManagementDB(
    unittest.TestCase
):

    PASSWORD = (
        "Mama-AI-Strong-Password-2026"
    )
    NEW_PASSWORD = (
        "Mama-AI-New-Strong-Password-2026"
    )

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.database_path = (
            Path(
                self.temp_directory.name
            )
            / "session-management.db"
        )
        self.store = (
            SQLiteAuthenticationStore(
                self.database_path
            )
        )

        self.first_user = self.store.create_user(
            email="first@example.com",
            password=self.PASSWORD,
        )
        self.second_user = self.store.create_user(
            email="second@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def create_session(
        self,
        *,
        user_id: str,
        suffix: str,
    ) -> dict:
        return self.store.create_session(
            user_id=user_id,
            refresh_token=(
                "mama-session-management-"
                + suffix
                + ("x" * 48)
            ),
            device_name=(
                "Device " + suffix
            ),
            expires_in_seconds=3600,
        )

    def test_list_sessions_is_scoped_to_user(
        self,
    ) -> None:
        self.create_session(
            user_id=self.first_user[
                "user_id"
            ],
            suffix="one",
        )
        self.create_session(
            user_id=self.second_user[
                "user_id"
            ],
            suffix="two",
        )

        sessions = self.store.list_sessions(
            user_id=self.first_user[
                "user_id"
            ]
        )

        self.assertEqual(
            len(sessions),
            1,
        )
        self.assertEqual(
            sessions[0]["user_id"],
            self.first_user["user_id"],
        )

    def test_revoke_user_session(
        self,
    ) -> None:
        session = self.create_session(
            user_id=self.first_user[
                "user_id"
            ],
            suffix="own",
        )

        revoked = self.store.revoke_user_session(
            user_id=self.first_user[
                "user_id"
            ],
            session_id=session[
                "session_id"
            ],
        )

        self.assertEqual(
            revoked["status"],
            "revoked",
        )

    def test_other_users_session_is_hidden(
        self,
    ) -> None:
        session = self.create_session(
            user_id=self.second_user[
                "user_id"
            ],
            suffix="other",
        )

        with self.assertRaises(
            KeyError
        ):
            self.store.revoke_user_session(
                user_id=self.first_user[
                    "user_id"
                ],
                session_id=session[
                    "session_id"
                ],
            )

        self.assertEqual(
            self.store.get_session(
                session["session_id"]
            )["status"],
            "active",
        )

    def test_change_password_revokes_sessions(
        self,
    ) -> None:
        self.create_session(
            user_id=self.first_user[
                "user_id"
            ],
            suffix="password-one",
        )
        self.create_session(
            user_id=self.first_user[
                "user_id"
            ],
            suffix="password-two",
        )

        result = self.store.change_password(
            user_id=self.first_user[
                "user_id"
            ],
            current_password=self.PASSWORD,
            new_password=self.NEW_PASSWORD,
        )

        self.assertEqual(
            result["revoked_sessions"],
            2,
        )
        self.assertFalse(
            self.store.verify_user_password(
                email="first@example.com",
                password=self.PASSWORD,
            )
        )
        self.assertTrue(
            self.store.verify_user_password(
                email="first@example.com",
                password=self.NEW_PASSWORD,
            )
        )

    def test_wrong_current_password_changes_nothing(
        self,
    ) -> None:
        session = self.create_session(
            user_id=self.first_user[
                "user_id"
            ],
            suffix="wrong-current",
        )

        with self.assertRaises(
            PermissionError
        ):
            self.store.change_password(
                user_id=self.first_user[
                    "user_id"
                ],
                current_password=(
                    "Wrong-current-password"
                ),
                new_password=self.NEW_PASSWORD,
            )

        self.assertTrue(
            self.store.verify_user_password(
                email="first@example.com",
                password=self.PASSWORD,
            )
        )
        self.assertEqual(
            self.store.get_session(
                session["session_id"]
            )["status"],
            "active",
        )

    def test_same_password_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.store.change_password(
                user_id=self.first_user[
                    "user_id"
                ],
                current_password=self.PASSWORD,
                new_password=self.PASSWORD,
            )

    def test_new_raw_password_is_not_stored(
        self,
    ) -> None:
        self.store.change_password(
            user_id=self.first_user[
                "user_id"
            ],
            current_password=self.PASSWORD,
            new_password=self.NEW_PASSWORD,
        )

        self.assertNotIn(
            self.NEW_PASSWORD.encode(
                "utf-8"
            ),
            self.database_path.read_bytes(),
        )

        with sqlite3.connect(
            self.database_path
        ) as connection:
            active = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {SESSION_TABLE}
                WHERE
                    user_id = ?
                    AND status = 'active'
                """,
                (
                    self.first_user[
                        "user_id"
                    ],
                ),
            ).fetchone()[0]

        self.assertEqual(
            active,
            0,
        )


if __name__ == "__main__":
    unittest.main()
