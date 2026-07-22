import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.middleware import rate_limit_store
from main import app


class TestSecurityEventHTTPIntegration(
    unittest.TestCase
):

    TOKEN = (
        "mama-security-event-integration-"
        + ("s" * 48)
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
                "RATE_LIMIT_WINDOW_SECONDS",
                60,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_GENERAL_REQUESTS",
                100,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_CHAT_REQUESTS",
                30,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_MEMORY_WRITE_REQUESTS",
                20,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_ACTION_REQUESTS",
                20,
            ),
            patch.object(
                settings,
                "AUTH_FAILURE_LIMIT",
                5,
            ),
            patch.object(
                settings,
                "AUTH_FAILURE_WINDOW_SECONDS",
                60,
            ),
            patch.object(
                settings,
                "AUTH_COOLDOWN_SECONDS",
                300,
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
        token: str | None = None,
    ) -> dict[str, str]:
        return {
            "Authorization": (
                "Bearer "
                + (
                    self.TOKEN
                    if token is None
                    else token
                )
            )
        }

    @staticmethod
    def event_types(
        mock_recorder,
    ) -> list[str]:
        return [
            call.kwargs["event_type"]
            for call in (
                mock_recorder.call_args_list
            )
        ]

    def test_invalid_token_and_auth_failure_are_recorded(
        self,
    ) -> None:
        with (
            patch(
                "app.api.auth."
                "record_security_event_safely"
            ) as auth_recorder,
            patch(
                "app.middleware.rate_limiter."
                "record_security_event_safely"
            ) as rate_recorder,
        ):
            response = self.client.get(
                "/history",
                headers=(
                    self.authorization_headers(
                        "invalid-token-value"
                    )
                ),
            )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertIn(
            "invalid_token",
            self.event_types(
                auth_recorder
            ),
        )
        self.assertIn(
            "authentication_failed",
            self.event_types(
                rate_recorder
            ),
        )

        for call in (
            auth_recorder.call_args_list
            + rate_recorder.call_args_list
        ):
            serialized = str(
                call.kwargs
            )
            self.assertNotIn(
                "invalid-token-value",
                serialized,
            )
            self.assertNotIn(
                self.TOKEN,
                serialized,
            )

    def test_owner_mismatch_is_recorded(
        self,
    ) -> None:
        with patch(
            "app.api.auth."
            "record_security_event_safely"
        ) as recorder:
            response = self.client.get(
                "/queue",
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
        self.assertIn(
            "owner_mismatch",
            self.event_types(
                recorder
            ),
        )
        self.assertNotIn(
            "other-user",
            str(
                recorder.call_args_list
            ),
        )

    def test_security_configuration_error_is_recorded(
        self,
    ) -> None:
        with (
            patch.object(
                settings,
                "AUTH_TOKEN",
                "short",
            ),
            patch(
                "app.api.auth."
                "record_security_event_safely"
            ) as recorder,
        ):
            response = self.client.get(
                "/auth/me",
                headers=(
                    self.authorization_headers()
                ),
            )

        self.assertEqual(
            response.status_code,
            503,
        )
        self.assertIn(
            "security_configuration_error",
            self.event_types(
                recorder
            ),
        )

    def test_general_rate_limit_is_recorded(
        self,
    ) -> None:
        with (
            patch.object(
                settings,
                "RATE_LIMIT_GENERAL_REQUESTS",
                1,
            ),
            patch(
                "app.middleware.rate_limiter."
                "record_security_event_safely"
            ) as recorder,
        ):
            first = self.client.get("/")
            second = self.client.get("/")

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            429,
        )
        self.assertIn(
            "rate_limit_exceeded",
            self.event_types(
                recorder
            ),
        )

    def test_cooldown_start_and_block_are_recorded(
        self,
    ) -> None:
        with (
            patch.object(
                settings,
                "AUTH_FAILURE_LIMIT",
                2,
            ),
            patch.object(
                settings,
                "AUTH_COOLDOWN_SECONDS",
                120,
            ),
            patch(
                "app.middleware.rate_limiter."
                "record_security_event_safely"
            ) as recorder,
        ):
            first = self.client.get(
                "/history",
                headers=(
                    self.authorization_headers(
                        "invalid-one"
                    )
                ),
            )
            second = self.client.get(
                "/history",
                headers=(
                    self.authorization_headers(
                        "invalid-two"
                    )
                ),
            )
            third = self.client.get(
                "/auth/me",
                headers=(
                    self.authorization_headers()
                ),
            )

        self.assertEqual(
            first.status_code,
            401,
        )
        self.assertEqual(
            second.status_code,
            429,
        )
        self.assertEqual(
            third.status_code,
            429,
        )

        recorded_types = self.event_types(
            recorder
        )

        self.assertIn(
            "authentication_failed",
            recorded_types,
        )
        self.assertIn(
            "authentication_cooldown_started",
            recorded_types,
        )
        self.assertIn(
            "authentication_cooldown_blocked",
            recorded_types,
        )

    def test_missing_token_records_authentication_failure(
        self,
    ) -> None:
        with patch(
            "app.middleware.rate_limiter."
            "record_security_event_safely"
        ) as recorder:
            response = self.client.get(
                "/history"
            )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertIn(
            "authentication_failed",
            self.event_types(
                recorder
            ),
        )


if __name__ == "__main__":
    unittest.main()
