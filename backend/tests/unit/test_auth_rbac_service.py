import tempfile
import unittest
from pathlib import Path

from app.core.auth_service import (
    AccountAdministrationConflictError,
    AccountAuthorizationError,
    AuthenticationService,
)
from app.core.rbac import ROLE_ADMIN, ROLE_AUDITOR, ROLE_USER
from app.database.auth_db import SQLiteAuthenticationStore


class TestAuthenticationRBACService(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    SECRET = "mama-rbac-service-secret-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "rbac-service.db"
        )
        self.service = AuthenticationService(
            store=self.store,
            signing_secret=self.SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
        )
        self.admin = self.service.register(
            email="admin@example.com",
            password=self.PASSWORD,
        )
        self.user = self.service.register(
            email="user@example.com",
            password=self.PASSWORD,
        )
        self.store.assign_user_role(
            user_id=self.admin["user_id"],
            role=ROLE_ADMIN,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_user_cannot_read_account_directory(self) -> None:
        with self.assertRaises(AccountAuthorizationError):
            self.service.list_accounts(
                actor_roles=(ROLE_USER,),
            )

    def test_auditor_can_read_but_cannot_modify_accounts(self) -> None:
        result = self.service.list_accounts(
            actor_roles=(ROLE_USER, ROLE_AUDITOR),
        )
        self.assertEqual(result["total"], 2)
        with self.assertRaises(AccountAuthorizationError):
            self.service.assign_account_role(
                actor_user_id=self.user["user_id"],
                actor_roles=(ROLE_USER, ROLE_AUDITOR),
                user_id=self.user["user_id"],
                role=ROLE_ADMIN,
            )

    def test_admin_can_assign_auditor_role(self) -> None:
        result = self.service.assign_account_role(
            actor_user_id=self.admin["user_id"],
            actor_roles=(ROLE_USER, ROLE_ADMIN),
            user_id=self.user["user_id"],
            role=ROLE_AUDITOR,
        )
        self.assertIn(ROLE_AUDITOR, result["user"]["roles"])

    def test_status_management_requires_admin_permission(self) -> None:
        with self.assertRaises(AccountAuthorizationError):
            self.service.disable_account(
                actor_user_id=self.user["user_id"],
                actor_roles=(ROLE_USER,),
                user_id=self.admin["user_id"],
            )

    def test_admin_can_disable_enable_and_unlock_accounts(self) -> None:
        disabled = self.service.disable_account(
            actor_user_id=self.admin["user_id"],
            actor_roles=(ROLE_USER, ROLE_ADMIN),
            user_id=self.user["user_id"],
        )
        self.assertEqual(disabled["user"]["status"], "disabled")
        enabled = self.service.enable_account(
            actor_user_id=self.admin["user_id"],
            actor_roles=(ROLE_USER, ROLE_ADMIN),
            user_id=self.user["user_id"],
        )
        self.assertEqual(enabled["user"]["status"], "active")
        self.store.set_user_status(
            user_id=self.user["user_id"],
            status="locked",
        )
        unlocked = self.service.unlock_account(
            actor_user_id=self.admin["user_id"],
            actor_roles=(ROLE_USER, ROLE_ADMIN),
            user_id=self.user["user_id"],
        )
        self.assertEqual(unlocked["user"]["status"], "active")

    def test_final_admin_safety_is_exposed_as_conflict(self) -> None:
        with self.assertRaises(AccountAdministrationConflictError):
            self.service.disable_account(
                actor_user_id="static-administrator",
                actor_roles=(ROLE_ADMIN,),
                user_id=self.admin["user_id"],
            )

    def test_existing_access_token_uses_current_database_roles(self) -> None:
        tokens = self.service.login(
            email="user@example.com",
            password=self.PASSWORD,
        )
        before = self.service.authenticate_access_token(
            tokens["access_token"]
        )
        self.assertEqual(before["user"]["roles"], [ROLE_USER])
        self.store.assign_user_role(
            user_id=self.user["user_id"],
            role=ROLE_AUDITOR,
        )
        after = self.service.authenticate_access_token(
            tokens["access_token"]
        )
        self.assertIn(ROLE_AUDITOR, after["user"]["roles"])


if __name__ == "__main__":
    unittest.main()
