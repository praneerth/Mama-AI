import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.api.chat import (
    ChatRequest,
    chat,
)
from app.core.engine import engine
from app.database.idempotency_db import (
    IdempotencyConflictError,
)


class TestChatIdempotency(
    unittest.TestCase
):

    KEY = (
        "mama-chat-idempotency-key-0001"
    )

    def setUp(self) -> None:
        engine.registry.clear()

    def tearDown(self) -> None:
        engine.registry.clear()

    @staticmethod
    def response_json(
        response: JSONResponse,
    ) -> dict:
        return json.loads(
            response.body.decode(
                "utf-8"
            )
        )

    @patch(
        "app.api.chat.idempotency_store.reserve"
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_missing_key_preserves_legacy_behavior(
        self,
        mock_process_request,
        mock_reserve,
    ) -> None:
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        response = chat(
            ChatRequest(
                message="hello"
            )
        )

        self.assertIsInstance(
            response,
            dict,
        )
        self.assertEqual(
            response["response"],
            "Hello",
        )
        mock_reserve.assert_not_called()

    @patch(
        "app.api.chat.idempotency_store.complete"
    )
    @patch(
        "app.api.chat.idempotency_store.reserve"
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_new_keyed_request_is_completed(
        self,
        mock_process_request,
        mock_reserve,
        mock_complete,
    ) -> None:
        mock_reserve.return_value = {
            "created": True,
            "status": "processing",
            "record_id": "record-1",
        }
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        response = chat(
            ChatRequest(
                message="hello"
            ),
            idempotency_key=self.KEY,
        )

        self.assertIsInstance(
            response,
            JSONResponse,
        )
        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.headers[
                "idempotency-replayed"
            ],
            "false",
        )

        payload = self.response_json(
            response
        )

        self.assertEqual(
            payload["response"],
            "Hello",
        )

        mock_complete.assert_called_once()

    @patch(
        "app.api.chat.idempotency_store.reserve"
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_completed_request_is_replayed(
        self,
        mock_process_request,
        mock_reserve,
    ) -> None:
        mock_reserve.return_value = {
            "created": False,
            "status": "completed",
            "record_id": "record-1",
            "response_status_code": 200,
            "response_body": {
                "success": True,
                "task_id": "task-1",
            },
        }

        response = chat(
            ChatRequest(
                message="open chrome"
            ),
            idempotency_key=self.KEY,
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.headers[
                "idempotency-replayed"
            ],
            "true",
        )
        self.assertEqual(
            self.response_json(
                response
            )["task_id"],
            "task-1",
        )
        mock_process_request.assert_not_called()

    @patch(
        "app.api.chat.idempotency_store.reserve"
    )
    def test_processing_request_returns_409(
        self,
        mock_reserve,
    ) -> None:
        mock_reserve.return_value = {
            "created": False,
            "status": "processing",
            "record_id": "record-1",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="open chrome"
                ),
                idempotency_key=self.KEY,
            )

        self.assertEqual(
            context.exception.status_code,
            409,
        )
        self.assertEqual(
            context.exception.headers[
                "Retry-After"
            ],
            "2",
        )

    @patch(
        "app.api.chat.idempotency_store.reserve",
        side_effect=IdempotencyConflictError(
            "different request"
        ),
    )
    def test_key_reuse_with_different_payload_returns_409(
        self,
        mock_reserve,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="different message"
                ),
                idempotency_key=self.KEY,
            )

        self.assertEqual(
            context.exception.status_code,
            409,
        )

    @patch(
        "app.api.chat.idempotency_store.reserve",
        side_effect=ValueError(
            "Idempotency-Key must contain at least "
            "16 characters."
        ),
    )
    def test_invalid_key_returns_400(
        self,
        mock_reserve,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="hello"
                ),
                idempotency_key="short",
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

    @patch(
        "app.api.chat.idempotency_store.fail"
    )
    @patch(
        "app.api.chat.idempotency_store.reserve"
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
    def test_queue_failure_is_stored(
        self,
        mock_process_request,
        mock_enqueue,
        mock_reserve,
        mock_fail,
    ) -> None:
        mock_reserve.return_value = {
            "created": True,
            "status": "processing",
            "record_id": "record-1",
        }
        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="open chrome"
                ),
                idempotency_key=self.KEY,
            )

        self.assertEqual(
            context.exception.status_code,
            503,
        )
        mock_fail.assert_called_once()

        fail_call = (
            mock_fail.call_args.kwargs
        )

        self.assertEqual(
            fail_call["error_code"],
            "queue_unavailable",
        )
        self.assertEqual(
            fail_call[
                "response_status_code"
            ],
            503,
        )

    @patch(
        "app.api.chat.idempotency_store.complete",
        side_effect=RuntimeError(
            "Database unavailable"
        ),
    )
    @patch(
        "app.api.chat.idempotency_store.reserve"
    )
    @patch(
        "app.api.chat.process_request"
    )
    def test_completion_failure_returns_503(
        self,
        mock_process_request,
        mock_reserve,
        mock_complete,
    ) -> None:
        mock_reserve.return_value = {
            "created": True,
            "status": "processing",
            "record_id": "record-1",
        }
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="hello"
                ),
                idempotency_key=self.KEY,
            )

        self.assertEqual(
            context.exception.status_code,
            503,
        )


if __name__ == "__main__":
    unittest.main()
