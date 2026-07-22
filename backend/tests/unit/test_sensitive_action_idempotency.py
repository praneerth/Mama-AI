import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.api.idempotency import (
    complete_sensitive_action,
    fail_sensitive_action,
    reserve_sensitive_action,
)
from app.database.idempotency_db import (
    IdempotencyConflictError,
)


class TestSensitiveActionIdempotency(
    unittest.TestCase
):

    KEY = (
        "mama-sensitive-action-key-0001"
    )

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
        "app.api.idempotency."
        "idempotency_store.reserve"
    )
    def test_missing_key_skips_storage(
        self,
        mock_reserve,
    ) -> None:
        response = reserve_sensitive_action(
            idempotency_key=None,
            owner_id="local-user",
            action_path=(
                "/tasks/task-1/cancel"
            ),
            request_payload={
                "action": "cancel",
            },
        )

        self.assertIsNone(response)
        mock_reserve.assert_not_called()

    @patch(
        "app.api.idempotency."
        "idempotency_store.reserve"
    )
    def test_new_reservation_returns_none(
        self,
        mock_reserve,
    ) -> None:
        mock_reserve.return_value = {
            "created": True,
            "status": "processing",
        }

        response = reserve_sensitive_action(
            idempotency_key=self.KEY,
            owner_id="local-user",
            action_path=(
                "/tasks/task-1/cancel"
            ),
            request_payload={
                "action": "cancel",
            },
        )

        self.assertIsNone(response)

        call = mock_reserve.call_args.kwargs

        self.assertEqual(
            call["request_path"],
            "/sensitive-actions",
        )
        self.assertEqual(
            call["request_payload"][
                "action_path"
            ],
            "/tasks/task-1/cancel",
        )

    @patch(
        "app.api.idempotency."
        "idempotency_store.reserve"
    )
    def test_completed_response_is_replayed(
        self,
        mock_reserve,
    ) -> None:
        mock_reserve.return_value = {
            "created": False,
            "status": "completed",
            "record_id": "record-1",
            "response_status_code": 200,
            "response_body": {
                "success": True,
            },
        }

        response = reserve_sensitive_action(
            idempotency_key=self.KEY,
            owner_id="local-user",
            action_path=(
                "/tasks/task-1/cancel"
            ),
            request_payload={
                "action": "cancel",
            },
        )

        self.assertIsInstance(
            response,
            JSONResponse,
        )
        self.assertEqual(
            response.headers[
                "idempotency-replayed"
            ],
            "true",
        )
        self.assertTrue(
            self.response_json(
                response
            )["success"]
        )

    @patch(
        "app.api.idempotency."
        "idempotency_store.reserve"
    )
    def test_processing_response_returns_409(
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
            reserve_sensitive_action(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                action_path=(
                    "/tasks/task-1/cancel"
                ),
                request_payload={
                    "action": "cancel",
                },
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
        "app.api.idempotency."
        "idempotency_store.reserve",
        side_effect=(
            IdempotencyConflictError(
                "different request"
            )
        ),
    )
    def test_conflict_returns_409(
        self,
        mock_reserve,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            reserve_sensitive_action(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                action_path=(
                    "/tasks/task-1/retry"
                ),
                request_payload={
                    "action": "retry",
                },
            )

        self.assertEqual(
            context.exception.status_code,
            409,
        )

    @patch(
        "app.api.idempotency."
        "idempotency_store.reserve",
        side_effect=ValueError(
            "Idempotency-Key must contain "
            "at least 16 characters."
        ),
    )
    def test_invalid_key_returns_400(
        self,
        mock_reserve,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            reserve_sensitive_action(
                idempotency_key="short",
                owner_id="local-user",
                action_path=(
                    "/tasks/task-1/retry"
                ),
                request_payload={
                    "action": "retry",
                },
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

    @patch(
        "app.api.idempotency."
        "idempotency_store.complete"
    )
    def test_complete_returns_fresh_response(
        self,
        mock_complete,
    ) -> None:
        response = (
            complete_sensitive_action(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                response_body={
                    "success": True,
                },
            )
        )

        self.assertIsInstance(
            response,
            JSONResponse,
        )
        self.assertEqual(
            response.headers[
                "idempotency-replayed"
            ],
            "false",
        )
        mock_complete.assert_called_once()

    @patch(
        "app.api.idempotency."
        "idempotency_store.fail",
        side_effect=RuntimeError(
            "database unavailable"
        ),
    )
    def test_failure_storage_is_fail_open(
        self,
        mock_fail,
    ) -> None:
        with self.assertLogs(
            "mama_ai.sensitive_idempotency",
            level="ERROR",
        ):
            fail_sensitive_action(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                status_code=409,
                detail="Action conflict.",
                error_code=(
                    "action_conflict"
                ),
            )

        mock_fail.assert_called_once()


if __name__ == "__main__":
    unittest.main()
