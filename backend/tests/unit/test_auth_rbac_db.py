import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.rbac import ROLE_ADMIN, ROLE_AUDITOR, ROLE_USER
from app.database.auth_db import (
    USER_ROLE_TABLE,
    SQLiteAuthenticationStore,
)


class TestAuthenticationRBACDB(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "rbac.db"
        self.store = SQLiteAuthenticationStore(self.database_path)
        self.admin = self.store.create_user(
            email="admin@example.com",
            password=self.PASSWORD,
        )
        self.user = self.store.create_user(
            email="user@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def make_admin(self, user_id: str):
        return self.store.assign_user_role(
            user_id=user_id,
            role=ROLE_ADMIN,
        )

    def test_schema_and_new_accounts_have_baseline_user_role(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (USER_ROLE_TABLE,),
            ).fetchone()
        self.assertIsNotNone(table)
        self.assertEqual(self.admin["roles"], [ROLE_USER])

    def test_existing_accounts_are_migrated_to_user_role(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(f"DROP TABLE {USER_ROLE_TABLE}")
        self.store.initialize()
        loaded = self.store.get_user(self.admin["user_id"])
        self.assertEqual(loaded["roles"], [ROLE_USER])

    def test_roles_can_be_assigned_and_non_baseline_roles_removed(self) -> None:
        assigned = self.store.assign_user_role(
            user_id=self.user["user_id"],
            role=ROLE_AUDITOR,
        )
        self.assertTrue(assigned["changed"])
        self.assertIn(ROLE_AUDITOR, assigned["user"]["roles"])
        removed = self.store.remove_user_role_by_administrator(
            actor_user_id=self.admin["user_id"],
            user_id=self.user["user_id"],
            role=ROLE_AUDITOR,
        )
        self.assertTrue(removed["changed"])
        self.assertNotIn(ROLE_AUDITOR, removed["user"]["roles"])

    def test_baseline_user_role_cannot_be_removed(self) -> None:
        with self.assertRaises(PermissionError):
            self.store.remove_user_role_by_administrator(
                actor_user_id=self.admin["user_id"],
                user_id=self.user["user_id"],
                role=ROLE_USER,
            )

    def test_administrator_cannot_remove_own_admin_role(self) -> None:
        self.make_admin(self.admin["user_id"])
        with self.assertRaises(PermissionError):
            self.store.remove_user_role_by_administrator(
                actor_user_id=self.admin["user_id"],
                user_id=self.admin["user_id"],
                role=ROLE_ADMIN,
            )

    def test_final_active_admin_role_cannot_be_removed(self) -> None:
        self.make_admin(self.admin["user_id"])
        with self.assertRaises(PermissionError):
            self.store.remove_user_role_by_administrator(
                actor_user_id="static-administrator",
                user_id=self.admin["user_id"],
                role=ROLE_ADMIN,
            )

    def test_admin_role_can_be_removed_when_another_active_admin_exists(self) -> None:
        self.make_admin(self.admin["user_id"])
        self.make_admin(self.user["user_id"])
        result = self.store.remove_user_role_by_administrator(
            actor_user_id="static-administrator",
            user_id=self.user["user_id"],
            role=ROLE_ADMIN,
        )
        self.assertTrue(result["changed"])
        self.assertNotIn(ROLE_ADMIN, result["user"]["roles"])

    def test_administrator_cannot_disable_own_account(self) -> None:
        self.make_admin(self.admin["user_id"])
        with self.assertRaises(PermissionError):
            self.store.set_user_status_by_administrator(
                actor_user_id=self.admin["user_id"],
                user_id=self.admin["user_id"],
                status="disabled",
                allowed_current_statuses={"active"},
            )

    def test_final_active_admin_account_cannot_be_disabled(self) -> None:
        self.make_admin(self.admin["user_id"])
        with self.assertRaises(PermissionError):
            self.store.set_user_status_by_administrator(
                actor_user_id="static-administrator",
                user_id=self.admin["user_id"],
                status="disabled",
                allowed_current_statuses={"active"},
            )

    def test_disabling_account_revokes_sessions(self) -> None:
        session = self.store.create_session(
            user_id=self.user["user_id"],
            refresh_token="rbac-refresh-" + ("r" * 48),
            expires_in_seconds=3600,
        )
        result = self.store.set_user_status_by_administrator(
            actor_user_id=self.admin["user_id"],
            user_id=self.user["user_id"],
            status="disabled",
            allowed_current_statuses={"active"},
        )
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertEqual(
            self.store.get_session(session["session_id"])["status"],
            "revoked",
        )

    def test_list_and_count_users_can_filter_by_role(self) -> None:
        self.store.assign_user_role(
            user_id=self.user["user_id"],
            role=ROLE_AUDITOR,
        )
        users = self.store.list_users(role=ROLE_AUDITOR)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["user_id"], self.user["user_id"])
        self.assertEqual(self.store.count_users(role=ROLE_AUDITOR), 1)


if __name__ == "__main__":
    unittest.main()
