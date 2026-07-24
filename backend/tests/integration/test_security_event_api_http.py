import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.security import router as security_router
from app.config import settings


app = FastAPI()
app.include_router(security_router)


class TestSecurityEventAPIHTTPIntegration(unittest.TestCase):

    TOKEN = "mama-security-api-integration-" + ("q" * 48)

    def setUp(self) -> None:
        self.settings_patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "AUTH_OWNER_ID", "local-user"),
            patch.object(settings, "AUTH_TOKEN", self.TOKEN),
            patch.object(
                settings,
                "AUTH_STATIC_COMPATIBILITY_ENABLED",
                True,
            ),
        ]
        for patcher in self.settings_patchers:
            patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self.settings_patchers):
            patcher.stop()

    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.TOKEN}

    def test_security_events_require_authentication(self) -> None:
        response = self.client.get("/security/events")
        self.assertEqual(response.status_code, 401)

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "user")
    def test_user_role_cannot_read_security_events(self) -> None:
        with patch("app.api.auth.record_security_event_safely") as recorder:
            response = self.client.get(
                "/security/events",
                headers=self.headers(),
            )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(recorder.called)
        self.assertEqual(
            recorder.call_args.kwargs["event_type"],
            "authorization_denied",
        )

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "auditor,user",
    )
    @patch("app.api.security.security_event_store.list")
    def test_auditor_can_filter_cross_user_events(self, mock_list) -> None:
        mock_list.return_value = [
            {
                "event_id": "event-1",
                "event_type": "invalid_token",
                "severity": "warning",
                "owner_id": "other-user",
            }
        ]
        response = self.client.get(
            "/security/events",
            headers=self.headers(),
            params={"owner_id": "other-user"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["owner_filter"], "other-user")
        mock_list.assert_called_once_with(
            event_type=None,
            severity=None,
            client_ref=None,
            owner_id="other-user",
            limit=100,
        )

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "admin,user",
    )
    @patch("app.api.security.security_event_store.list")
    def test_admin_can_read_global_summary(self, mock_list) -> None:
        mock_list.return_value = []
        response = self.client.get(
            "/security/events/summary",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total"], 0)
        self.assertIsNone(response.json()["owner_filter"])

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "auditor,user",
    )
    @patch(
        "app.api.security.security_event_store.get",
        return_value=None,
    )
    def test_missing_event_returns_404(self, mock_get) -> None:
        response = self.client.get(
            "/security/events/missing",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 404)

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "auditor,user",
    )
    def test_empty_owner_filter_returns_400(self) -> None:
        response = self.client.get(
            "/security/events",
            headers=self.headers(),
            params={"owner_id": "   "},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
