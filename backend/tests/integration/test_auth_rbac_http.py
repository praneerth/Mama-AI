import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.config import settings
from app.core.auth_service import authentication_service
from app.core.rbac import ROLE_ADMIN, ROLE_AUDITOR
from app.database.auth_db import SQLiteAuthenticationStore


app = FastAPI()
app.include_router(auth_router)
app.include_router(admin_router)


class TestAuthenticationRBACHTTP(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    SIGNING_SECRET = "mama-rbac-http-signing-" + ("s" * 48)
    STATIC_TOKEN = "mama-rbac-static-token-" + ("t" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_store = authentication_service._store
        authentication_service._store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "rbac-http.db"
        )
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "ACCOUNT_AUTH_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "admin,auditor,user"),
            patch.object(settings, "AUTH_OWNER_ID", "local-user"),
            patch.object(settings, "AUTH_TOKEN", self.STATIC_TOKEN),
            patch.object(settings, "AUTH_SIGNING_SECRET", self.SIGNING_SECRET),
            patch.object(settings, "AUTH_ACCESS_TOKEN_SECONDS", 900),
            patch.object(settings, "AUTH_REFRESH_TOKEN_SECONDS", 3600),
            patch.object(settings, "AUTH_TWO_FACTOR_ENABLED", False),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = TestClient(app)
        self.admin_one = self.register("admin1@example.com")
        self.admin_two = self.register("admin2@example.com")
        self.user = self.register("user@example.com")
        self.auditor = self.register("auditor@example.com")
        authentication_service._store.assign_user_role(
            user_id=self.admin_one["user_id"],
            role=ROLE_ADMIN,
        )
        authentication_service._store.assign_user_role(
            user_id=self.admin_two["user_id"],
            role=ROLE_ADMIN,
        )
        authentication_service._store.assign_user_role(
            user_id=self.auditor["user_id"],
            role=ROLE_AUDITOR,
        )

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        authentication_service._store = self.original_store
        self.temp_directory.cleanup()

    def register(self, email: str):
        response = self.client.post(
            "/auth/register",
            json={"email": email, "password": self.PASSWORD},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["user"]

    def login_headers(self, email: str):
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": self.PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        return {
            "Authorization": "Bearer " + response.json()["access_token"]
        }

    def static_headers(self):
        return {"Authorization": "Bearer " + self.STATIC_TOKEN}

    def test_user_cannot_list_accounts(self) -> None:
        response = self.client.get(
            "/auth/admin/accounts",
            headers=self.login_headers("user@example.com"),
        )
        self.assertEqual(response.status_code, 403)

    def test_auditor_can_read_but_cannot_modify(self) -> None:
        headers = self.login_headers("auditor@example.com")
        listed = self.client.get("/auth/admin/accounts", headers=headers)
        modified = self.client.post(
            f"/auth/admin/accounts/{self.user['user_id']}/roles/admin",
            headers=headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(modified.status_code, 403)

    def test_admin_can_list_filter_and_read_accounts(self) -> None:
        headers = self.login_headers("admin1@example.com")
        listed = self.client.get(
            "/auth/admin/accounts?role=admin",
            headers=headers,
        )
        loaded = self.client.get(
            f"/auth/admin/accounts/{self.user['user_id']}",
            headers=headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 2)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["user"]["email"], "user@example.com")

    def test_existing_token_gains_and_loses_permissions_immediately(self) -> None:
        user_headers = self.login_headers("user@example.com")
        admin_headers = self.login_headers("admin1@example.com")
        before = self.client.get("/auth/admin/accounts", headers=user_headers)
        assigned = self.client.post(
            f"/auth/admin/accounts/{self.user['user_id']}/roles/admin",
            headers=admin_headers,
        )
        after_assign = self.client.get(
            "/auth/admin/accounts", headers=user_headers
        )
        removed = self.client.delete(
            f"/auth/admin/accounts/{self.user['user_id']}/roles/admin",
            headers=admin_headers,
        )
        after_remove = self.client.get(
            "/auth/admin/accounts", headers=user_headers
        )
        self.assertEqual(before.status_code, 403)
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(after_assign.status_code, 200)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(after_remove.status_code, 403)

    def test_admin_cannot_disable_self_or_remove_own_admin_role(self) -> None:
        headers = self.login_headers("admin1@example.com")
        disabled = self.client.post(
            f"/auth/admin/accounts/{self.admin_one['user_id']}/disable",
            headers=headers,
        )
        removed = self.client.delete(
            f"/auth/admin/accounts/{self.admin_one['user_id']}/roles/admin",
            headers=headers,
        )
        self.assertEqual(disabled.status_code, 409)
        self.assertEqual(removed.status_code, 409)

    def test_final_active_admin_protection(self) -> None:
        headers = self.static_headers()
        first = self.client.delete(
            f"/auth/admin/accounts/{self.admin_two['user_id']}/roles/admin",
            headers=headers,
        )
        final = self.client.delete(
            f"/auth/admin/accounts/{self.admin_one['user_id']}/roles/admin",
            headers=headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(final.status_code, 409)

    def test_disabling_account_revokes_existing_access(self) -> None:
        user_headers = self.login_headers("user@example.com")
        admin_headers = self.login_headers("admin1@example.com")
        disabled = self.client.post(
            f"/auth/admin/accounts/{self.user['user_id']}/disable",
            headers=admin_headers,
        )
        after = self.client.get("/auth/me", headers=user_headers)
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.json()["revoked_sessions"], 1)
        self.assertEqual(after.status_code, 401)

    def test_locked_account_can_be_unlocked(self) -> None:
        authentication_service._store.set_user_status(
            user_id=self.user["user_id"],
            status="locked",
        )
        response = self.client.post(
            f"/auth/admin/accounts/{self.user['user_id']}/unlock",
            headers=self.login_headers("admin1@example.com"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["status"], "active")

    def test_static_compatibility_token_can_bootstrap_admin_role(self) -> None:
        response = self.client.post(
            f"/auth/admin/accounts/{self.user['user_id']}/roles/admin",
            headers=self.static_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(ROLE_ADMIN, response.json()["user"]["roles"])

    def test_administrative_event_omits_raw_email_and_token(self) -> None:
        with patch("app.api.admin.record_security_event_safely") as recorder:
            response = self.client.post(
                f"/auth/admin/accounts/{self.user['user_id']}/roles/auditor",
                headers=self.login_headers("admin1@example.com"),
            )
        self.assertEqual(response.status_code, 200)
        rendered = repr(recorder.call_args_list)
        self.assertNotIn("user@example.com", rendered)
        self.assertNotIn(self.STATIC_TOKEN, rendered)
        self.assertIn("role_assigned", rendered)


if __name__ == "__main__":
    unittest.main()
