import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.middleware import rate_limit_store
from main import app


class TestSecurityEventAPIHTTPIntegration(
    unittest.TestCase
):

    TOKEN = (
        "mama-security-api-integration-"
        + ("q" * 48)
    )

    def setUp(self) -> None:
        self.settings_patchers = [
            patch.object(
                settings,
                "AUTH_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "AUTH_OWNER_ID",
                "local-user",
            ),
            patch.object(
                settings,
                "AUTH_TOKEN",
                self.TOKEN,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_GENERAL_REQUESTS",
                100,
            ),
        ]

        for patcher in self.settings_patchers:
            patcher.start()

        rate_limit_store.reset()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()

        for patcher in reversed(
            self.settings_patchers
        ):
            patcher.stop()

    def authorization_headers(
        self,
    ) -> dict[str, str]:
        return {
            "Authorization": (
                "Bearer " + self.TOKEN
            )
        }

    def test_security_events_require_authentication(
        self,
    ) -> None:
        with patch(
            "app.middleware.rate_limiter."
            "record_security_event_safely"
        ):
            response = self.client.get(
                "/security/events"
            )

        self.assertEqual(
            response.status_code,
            401,
        )

    @patch(
        "app.api.security."
        "security_event_store.list"
    )
    def test_authenticated_event_list(
        self,
        mock_list,
    ) -> None:
        mock_list.return_value = [
            {
                "event_id": "event-1",
                "event_type": "invalid_token",
                "severity": "warning",
                "owner_id": "local-user",
            }
        ]

        response = self.client.get(
            "/security/events",
            headers=(
                self.authorization_headers()
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["count"],
            1,
        )

    @patch(
        "app.api.security."
        "security_event_store.list"
    )
    def test_authenticated_summary(
        self,
        mock_list,
    ) -> None:
        mock_list.return_value = []

        response = self.client.get(
            "/security/events/summary",
            headers=(
                self.authorization_headers()
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["summary"][
                "total"
            ],
            0,
        )

    @patch(
        "app.api.security."
        "security_event_store.get",
        return_value=None,
    )
    def test_missing_event_returns_404(
        self,
        mock_get,
    ) -> None:
        response = self.client.get(
            "/security/events/missing",
            headers=(
                self.authorization_headers()
            ),
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_other_owner_query_returns_403(
        self,
    ) -> None:
        response = self.client.get(
            "/security/events",
            headers=(
                self.authorization_headers()
            ),
            params={
                "owner_id": "other-user",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
