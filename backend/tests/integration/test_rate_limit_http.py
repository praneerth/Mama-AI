import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.middleware import rate_limit_store
from main import app


class TestRateLimitHTTPIntegration(
    unittest.TestCase
):

    TOKEN = (
        "mama-rate-limit-integration-"
        + ("r" * 48)
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

    def test_general_limit_returns_429_and_retry_after(
        self,
    ) -> None:
        with patch.object(
            settings,
            "RATE_LIMIT_GENERAL_REQUESTS",
            1,
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
        self.assertGreaterEqual(
            int(
                second.headers[
                    "Retry-After"
                ]
            ),
            1,
        )
        self.assertEqual(
            second.headers[
                "X-RateLimit-Category"
            ],
            "general",
        )

    def test_health_is_exempt_from_general_limit(
        self,
    ) -> None:
        with patch.object(
            settings,
            "RATE_LIMIT_GENERAL_REQUESTS",
            1,
        ):
            responses = [
                self.client.get(
                    "/health"
                )
                for _ in range(3)
            ]

        self.assertTrue(
            all(
                response.status_code
                == 200
                for response in responses
            )
        )

    @patch(
        "app.api.chat.process_request"
    )
    def test_chat_uses_specific_limit(
        self,
        mock_process_request,
    ) -> None:
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        with patch.object(
            settings,
            "RATE_LIMIT_CHAT_REQUESTS",
            1,
        ):
            first = self.client.post(
                "/chat",
                headers=(
                    self.authorization_headers()
                ),
                json={
                    "message": "Hello",
                },
            )

            second = self.client.post(
                "/chat",
                headers=(
                    self.authorization_headers()
                ),
                json={
                    "message": "Hello again",
                },
            )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            429,
        )
        self.assertEqual(
            second.headers[
                "X-RateLimit-Category"
            ],
            "chat",
        )

    def test_authentication_failures_start_cooldown(
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
        self.assertEqual(
            second.headers[
                "X-RateLimit-Category"
            ],
            "authentication_cooldown",
        )

    def test_rate_headers_are_added_to_allowed_response(
        self,
    ) -> None:
        response = self.client.get(
            "/auth/me",
            headers=self.authorization_headers(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.headers[
                "X-RateLimit-Category"
            ],
            "general",
        )
        self.assertIn(
            "X-RateLimit-Limit",
            response.headers,
        )
        self.assertIn(
            "X-RateLimit-Remaining",
            response.headers,
        )

    def test_security_log_does_not_contain_token(
        self,
    ) -> None:
        invalid_token = (
            "private-invalid-token-value"
        )

        with self.assertLogs(
            "mama_ai.rate_limit",
            level="WARNING",
        ) as captured:
            response = self.client.get(
                "/history",
                headers=(
                    self.authorization_headers(
                        invalid_token
                    )
                ),
            )

        self.assertEqual(
            response.status_code,
            401,
        )

        combined_logs = "\n".join(
            captured.output
        )

        self.assertNotIn(
            invalid_token,
            combined_logs,
        )
        self.assertNotIn(
            self.TOKEN,
            combined_logs,
        )


if __name__ == "__main__":
    unittest.main()
