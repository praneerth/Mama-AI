import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.core.engine import engine
from app.database.idempotency_db import (
    idempotency_store,
)
from app.middleware import rate_limit_store
from main import app


class TestChatIdempotencyHTTPIntegration(
    unittest.TestCase
):

    TOKEN = (
        "mama-chat-idempotency-http-"
        + ("i" * 48)
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
            patch.object(
                settings,
                "RATE_LIMIT_CHAT_REQUESTS",
                100,
            ),
        ]

        for patcher in self.settings_patchers:
            patcher.start()

        rate_limit_store.reset()
        idempotency_store.clear()
        engine.registry.clear()

        self.client = TestClient(
            app
        )

    def tearDown(self) -> None:
        self.client.close()

        rate_limit_store.reset()
        idempotency_store.clear()
        engine.registry.clear()

        for patcher in reversed(
            self.settings_patchers
        ):
            patcher.stop()

    def headers(
        self,
        key: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": (
                "Bearer " + self.TOKEN
            )
        }

        if key is not None:
            headers[
                "Idempotency-Key"
            ] = key

        return headers

    @patch(
        "app.api.chat.process_request"
    )
    def test_request_without_key_remains_supported(
        self,
        mock_process_request,
    ) -> None:
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        response = self.client.post(
            "/chat",
            headers=self.headers(),
            json={
                "message": "hello"
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["response"],
            "Hello",
        )
        self.assertNotIn(
            "Idempotency-Replayed",
            response.headers,
        )

    @patch(
        "app.api.chat.process_request"
    )
    def test_same_key_replays_general_chat_response(
        self,
        mock_process_request,
    ) -> None:
        key = (
            "mama-chat-http-key-general-0001"
        )

        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        first = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "hello"
            },
        )

        second = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "hello"
            },
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        self.assertEqual(
            first.json(),
            second.json(),
        )
        self.assertEqual(
            first.headers[
                "Idempotency-Replayed"
            ],
            "false",
        )
        self.assertEqual(
            second.headers[
                "Idempotency-Replayed"
            ],
            "true",
        )
        mock_process_request.assert_called_once_with(
            "hello"
        )

    @patch(
        "app.api.chat.task_worker.notify"
    )
    @patch(
        "app.api.chat.task_queue_store.enqueue"
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_automation_retry_does_not_create_second_task(
        self,
        mock_process_request,
        mock_enqueue,
        mock_notify,
    ) -> None:
        key = (
            "mama-chat-http-key-automation-0001"
        )

        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }
        mock_enqueue.return_value = {
            "status": "queued",
        }

        first = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "open chrome"
            },
        )

        second = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "open chrome"
            },
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        self.assertEqual(
            first.json()["task_id"],
            second.json()["task_id"],
        )
        self.assertEqual(
            len(
                engine.registry.list()
            ),
            1,
        )
        mock_process_request.assert_called_once()
        mock_enqueue.assert_called_once()
        mock_notify.assert_called_once()

    @patch(
        "app.api.chat.process_request"
    )
    def test_same_key_different_message_returns_409(
        self,
        mock_process_request,
    ) -> None:
        key = (
            "mama-chat-http-key-conflict-0001"
        )

        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        first = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "hello"
            },
        )

        second = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "different"
            },
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            409,
        )
        self.assertEqual(
            mock_process_request.call_count,
            1,
        )

    @patch(
        "app.api.chat.process_request"
    )
    def test_processing_request_returns_retry_after(
        self,
        mock_process_request,
    ) -> None:
        key = (
            "mama-chat-http-key-processing-0001"
        )

        idempotency_store.reserve(
            idempotency_key=key,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            request_payload={
                "message": "hello",
            },
        )

        response = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "hello"
            },
        )

        self.assertEqual(
            response.status_code,
            409,
        )
        self.assertEqual(
            response.headers[
                "Retry-After"
            ],
            "2",
        )
        self.assertEqual(
            response.headers[
                "Idempotency-Status"
            ],
            "processing",
        )
        mock_process_request.assert_not_called()

    def test_short_key_returns_400(
        self,
    ) -> None:
        response = self.client.post(
            "/chat",
            headers=self.headers(
                "short"
            ),
            json={
                "message": "hello"
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    @patch(
        "app.api.chat.task_queue_store.enqueue",
        side_effect=RuntimeError(
            "Queue unavailable"
        ),
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_failed_response_is_replayed(
        self,
        mock_process_request,
        mock_enqueue,
    ) -> None:
        key = (
            "mama-chat-http-key-failure-0001"
        )

        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }

        first = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "open chrome"
            },
        )

        second = self.client.post(
            "/chat",
            headers=self.headers(key),
            json={
                "message": "open chrome"
            },
        )

        self.assertEqual(
            first.status_code,
            503,
        )
        self.assertEqual(
            second.status_code,
            503,
        )
        self.assertEqual(
            first.json(),
            second.json(),
        )
        self.assertEqual(
            second.headers[
                "Idempotency-Replayed"
            ],
            "true",
        )
        mock_process_request.assert_called_once()
        mock_enqueue.assert_called_once()

    @patch(
        "app.api.chat.process_request"
    )
    def test_raw_key_is_not_returned_or_logged(
        self,
        mock_process_request,
    ) -> None:
        key = (
            "private-chat-idempotency-key-0001"
        )

        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        with self.assertLogs(
            "mama_ai",
            level="INFO",
        ) as captured:
            response = self.client.post(
                "/chat",
                headers=self.headers(key),
                json={
                    "message": "hello"
                },
            )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertNotIn(
            key,
            response.text,
        )
        self.assertNotIn(
            key,
            "\n".join(
                captured.output
            ),
        )


if __name__ == "__main__":
    unittest.main()
