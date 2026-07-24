import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import (
    AuthenticatedPrincipal,
    require_principal,
    router as auth_router,
)
from app.api.device_security import router as device_security_router
from app.config import settings
from app.core.auth_service import authentication_service
from app.core.device_security_service import device_security_service
from app.database.auth_db import SQLiteAuthenticationStore
from app.database.device_security_db import SQLiteDeviceSecurityStore


app = FastAPI()
app.include_router(auth_router)
app.include_router(device_security_router)


@app.post("/tasks/test-api-key-scope")
def automation_scope_probe(
    principal: AuthenticatedPrincipal = Depends(require_principal),
):
    return {"success": True, "owner_id": principal.owner_id}


@app.post("/ordinary-write")
def write_scope_probe(
    principal: AuthenticatedPrincipal = Depends(require_principal),
):
    return {"success": True, "owner_id": principal.owner_id}


class TestDeviceAPIKeySecurityHTTP(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    SIGNING_SECRET = "mama-device-http-signing-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "http.db"
        self.store = SQLiteAuthenticationStore(path)
        self.device_store = SQLiteDeviceSecurityStore(path)
        self.original_auth_store = authentication_service._store
        self.original_device_store = device_security_service._store
        self.original_device_auth_store = device_security_service._auth_store
        authentication_service._store = self.store
        device_security_service._store = self.device_store
        device_security_service._auth_store = self.store
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "ACCOUNT_AUTH_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", False),
            patch.object(settings, "AUTH_SIGNING_SECRET", self.SIGNING_SECRET),
            patch.object(settings, "AUTH_ACCESS_TOKEN_SECONDS", 900),
            patch.object(settings, "AUTH_REFRESH_TOKEN_SECONDS", 3600),
            patch.object(settings, "AUTH_TWO_FACTOR_ENABLED", False),
            patch.object(settings, "AUTH_TRUSTED_DEVICES_ENABLED", True),
            patch.object(settings, "AUTH_API_KEYS_ENABLED", True),
            patch.object(settings, "AUTH_API_KEY_MAX_ACTIVE", 10),
            patch.object(settings, "AUTH_API_KEY_DEFAULT_EXPIRY_DAYS", 30),
            patch.object(settings, "AUTH_API_KEY_MAX_EXPIRY_DAYS", 365),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = TestClient(app)
        self.register("first@example.com")
        self.register("second@example.com")

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        authentication_service._store = self.original_auth_store
        device_security_service._store = self.original_device_store
        device_security_service._auth_store = self.original_device_auth_store
        self.temp_directory.cleanup()

    def register(self, email: str) -> dict:
        response = self.client.post(
            "/auth/register",
            json={"email": email, "password": self.PASSWORD},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["user"]

    def login(self, email: str, client_ref: str) -> tuple[dict, dict]:
        response = self.client.post(
            "/auth/login",
            headers={"User-Agent": "Mama Desktop Test/1.0"},
            json={
                "email": email,
                "password": self.PASSWORD,
                "device_name": "Windows laptop",
                "client_ref": client_ref,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return body, {"Authorization": "Bearer " + body["access_token"]}

    def create_key(self, headers: dict, scopes: list[str]) -> dict:
        response = self.client.post(
            "/auth/security/api-keys",
            headers=headers,
            json={
                "name": "Mama CLI",
                "scopes": scopes,
                "current_password": self.PASSWORD,
                "expires_in_days": 30,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_login_registers_named_device_and_session_metadata(self) -> None:
        body, headers = self.login("first@example.com", "device-one")
        response = self.client.get("/auth/security/devices", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        devices = response.json()["devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_name"], "Windows laptop")
        sessions = self.client.get(
            f"/auth/security/devices/{devices[0]['device_id']}/sessions",
            headers=headers,
        )
        self.assertEqual(sessions.status_code, 200)
        self.assertEqual(sessions.json()["sessions"][0]["session_id"], body["session"]["session_id"])
        account_sessions = self.client.get("/auth/sessions", headers=headers)
        self.assertEqual(account_sessions.status_code, 200)
        linked = account_sessions.json()["sessions"][0]["device"]
        self.assertEqual(linked["device_id"], devices[0]["device_id"])

    def test_device_trust_and_revoke_invalidates_session(self) -> None:
        _, headers = self.login("first@example.com", "device-two")
        device = self.client.get(
            "/auth/security/devices", headers=headers
        ).json()["devices"][0]
        trusted = self.client.post(
            f"/auth/security/devices/{device['device_id']}/trust",
            headers=headers,
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(trusted.status_code, 200, trusted.text)
        self.assertTrue(trusted.json()["device"]["trusted"])
        revoked = self.client.post(
            f"/auth/security/devices/{device['device_id']}/revoke",
            headers=headers,
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["revoked_sessions"], 1)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_api_key_can_authenticate_read_request(self) -> None:
        _, headers = self.login("first@example.com", "device-three")
        created = self.create_key(headers, ["api.read"])
        key_headers = {"Authorization": "Bearer " + created["api_key"]}
        response = self.client.get("/auth/me", headers=key_headers)
        self.assertEqual(response.status_code, 200, response.text)
        principal = response.json()["principal"]
        self.assertEqual(principal["authentication_method"], "api_key")
        self.assertEqual(principal["api_key_id"], created["record"]["key_id"])
        self.assertNotIn(created["api_key"], repr(principal))

    def test_api_key_scopes_are_enforced(self) -> None:
        _, headers = self.login("first@example.com", "device-four")
        read_key = self.create_key(headers, ["api.read"])["api_key"]
        denied = self.client.post(
            "/ordinary-write",
            headers={"Authorization": "Bearer " + read_key},
        )
        self.assertEqual(denied.status_code, 403)
        automation_key = self.create_key(headers, ["automation.execute"])["api_key"]
        allowed = self.client.post(
            "/tasks/test-api-key-scope",
            headers={"Authorization": "Bearer " + automation_key},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_api_key_cannot_manage_account_security(self) -> None:
        _, headers = self.login("first@example.com", "device-five")
        raw = self.create_key(
            headers, ["api.read", "api.write", "automation.execute"]
        )["api_key"]
        response = self.client.get(
            "/auth/security/api-keys",
            headers={"Authorization": "Bearer " + raw},
        )
        self.assertEqual(response.status_code, 403)

    def test_revoked_api_key_is_rejected(self) -> None:
        _, headers = self.login("first@example.com", "device-six")
        created = self.create_key(headers, ["api.read"])
        revoked = self.client.post(
            f"/auth/security/api-keys/{created['record']['key_id']}/revoke",
            headers=headers,
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        response = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + created["api_key"]},
        )
        self.assertEqual(response.status_code, 401)

    def test_rotation_invalidates_old_key_and_returns_new_key_once(self) -> None:
        _, headers = self.login("first@example.com", "device-seven")
        created = self.create_key(headers, ["api.read"])
        rotated = self.client.post(
            f"/auth/security/api-keys/{created['record']['key_id']}/rotate",
            headers=headers,
            json={"current_password": self.PASSWORD, "expires_in_days": 60},
        )
        self.assertEqual(rotated.status_code, 200, rotated.text)
        new_key = rotated.json()["api_key"]
        self.assertNotEqual(new_key, created["api_key"])
        self.assertEqual(
            self.client.get(
                "/auth/me",
                headers={"Authorization": "Bearer " + created["api_key"]},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/auth/me", headers={"Authorization": "Bearer " + new_key}
            ).status_code,
            200,
        )
        listed = self.client.get("/auth/security/api-keys", headers=headers)
        self.assertNotIn(new_key, listed.text)

    def test_other_users_device_and_key_are_hidden(self) -> None:
        _, first_headers = self.login("first@example.com", "device-eight")
        _, second_headers = self.login("second@example.com", "device-nine")
        device = self.client.get(
            "/auth/security/devices", headers=first_headers
        ).json()["devices"][0]
        key = self.create_key(first_headers, ["api.read"])
        device_response = self.client.post(
            f"/auth/security/devices/{device['device_id']}/trust",
            headers=second_headers,
            json={"current_password": self.PASSWORD},
        )
        key_response = self.client.post(
            f"/auth/security/api-keys/{key['record']['key_id']}/revoke",
            headers=second_headers,
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(device_response.status_code, 404)
        self.assertEqual(key_response.status_code, 404)

    def test_password_change_revokes_all_api_keys(self) -> None:
        _, headers = self.login("first@example.com", "device-password")
        created = self.create_key(headers, ["api.read"])
        changed = self.client.post(
            "/auth/change-password",
            headers=headers,
            json={
                "current_password": self.PASSWORD,
                "new_password": "Mama-AI-New-Strong-Password-2026",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["revoked_api_keys"], 1)
        self.assertEqual(
            self.client.get(
                "/auth/me",
                headers={"Authorization": "Bearer " + created["api_key"]},
            ).status_code,
            401,
        )

    def test_security_event_does_not_include_raw_key_or_password(self) -> None:
        _, headers = self.login("first@example.com", "device-ten")
        with patch(
            "app.api.device_security.record_security_event_safely"
        ) as recorder:
            created = self.create_key(headers, ["api.read"])
        rendered = repr(recorder.call_args_list)
        self.assertNotIn(created["api_key"], rendered)
        self.assertNotIn(self.PASSWORD, rendered)
        self.assertIn("account_api_key_created", rendered)


if __name__ == "__main__":
    unittest.main()
