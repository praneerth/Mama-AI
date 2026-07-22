import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.idempotency import (
    reserve_sensitive_action,
)
from app.config import settings
from app.database.idempotency_db import (
    idempotency_store,
)
from app.middleware import rate_limit_store
from main import app


class TestSensitiveActionIdempotencyHTTP(
    unittest.TestCase
):

    TOKEN = (
        "mama-sensitive-http-token-"
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
                "RATE_LIMIT_GENERAL_REQUESTS",
                100,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_ACTION_REQUESTS",
                100,
            ),
        ]

        for patcher in self.settings_patchers:
            patcher.start()

        rate_limit_store.reset()
        idempotency_store.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()
        idempotency_store.clear()

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
        "app.api.approvals."
        "_approve_and_execute_core"
    )
    def test_approve_is_replayed(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-approve-key-0001"
        )
        mock_core.return_value = {
            "success": True,
            "approval": {
                "approval_id": "approval-1",
            },
            "task": {
                "task_id": "task-1",
            },
        }

        first = self.client.post(
            "/approvals/approval-1/approve",
            headers=self.headers(key),
            json={},
        )
        second = self.client.post(
            "/approvals/approval-1/approve",
            headers=self.headers(key),
            json={},
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
            second.headers[
                "Idempotency-Replayed"
            ],
            "true",
        )
        mock_core.assert_called_once_with(
            "approval-1",
            "local-user",
        )

    @patch(
        "app.api.approvals."
        "_reject_approval_core"
    )
    @patch(
        "app.api.approvals."
        "_approve_and_execute_core"
    )
    def test_same_key_cannot_change_action(
        self,
        mock_approve_core,
        mock_reject_core,
    ) -> None:
        key = (
            "mama-sensitive-action-conflict-0001"
        )
        mock_approve_core.return_value = {
            "success": True,
        }
        mock_reject_core.return_value = {
            "success": True,
        }

        first = self.client.post(
            "/approvals/approval-1/approve",
            headers=self.headers(key),
            json={},
        )
        second = self.client.post(
            "/approvals/approval-1/reject",
            headers=self.headers(key),
            json={},
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            409,
        )
        mock_approve_core.assert_called_once()
        mock_reject_core.assert_not_called()

    @patch(
        "app.api.approvals."
        "_reject_approval_core"
    )
    def test_reject_is_replayed(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-reject-key-0001"
        )
        mock_core.return_value = {
            "success": True,
        }

        first = self.client.post(
            "/approvals/approval-1/reject",
            headers=self.headers(key),
            json={},
        )
        second = self.client.post(
            "/approvals/approval-1/reject",
            headers=self.headers(key),
            json={},
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        mock_core.assert_called_once()

    @patch(
        "app.api.tasks._retry_task_core"
    )
    def test_retry_is_replayed(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-retry-key-0001"
        )
        mock_core.return_value = {
            "success": True,
            "queue": {
                "status": "queued",
            },
        }

        first = self.client.post(
            "/tasks/task-1/retry",
            headers=self.headers(key),
            params={
                "max_attempts": 4,
                "delay_seconds": 5,
            },
        )
        second = self.client.post(
            "/tasks/task-1/retry",
            headers=self.headers(key),
            params={
                "max_attempts": 4,
                "delay_seconds": 5,
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
        mock_core.assert_called_once_with(
            "task-1",
            max_attempts=4,
            delay_seconds=5,
        )

    @patch(
        "app.api.tasks._retry_task_core"
    )
    def test_retry_payload_change_returns_409(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-retry-conflict-0001"
        )
        mock_core.return_value = {
            "success": True,
        }

        first = self.client.post(
            "/tasks/task-1/retry",
            headers=self.headers(key),
            params={
                "max_attempts": 3,
                "delay_seconds": 0,
            },
        )
        second = self.client.post(
            "/tasks/task-1/retry",
            headers=self.headers(key),
            params={
                "max_attempts": 5,
                "delay_seconds": 0,
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
        mock_core.assert_called_once()

    @patch(
        "app.api.tasks._cancel_task_core"
    )
    def test_cancel_is_replayed(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-cancel-key-0001"
        )
        mock_core.return_value = {
            "success": True,
            "already_cancelled": False,
        }

        first = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(key),
        )
        second = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(key),
        )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        mock_core.assert_called_once_with(
            "task-1"
        )

    @patch(
        "app.api.tasks._cancel_task_core"
    )
    def test_failed_action_is_replayed(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-failure-key-0001"
        )
        mock_core.side_effect = (
            HTTPException(
                status_code=409,
                detail=(
                    "Task cannot be cancelled."
                ),
            )
        )

        first = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(key),
        )
        second = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(key),
        )

        self.assertEqual(
            first.status_code,
            409,
        )
        self.assertEqual(
            second.status_code,
            409,
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
        mock_core.assert_called_once()

    @patch(
        "app.api.tasks._cancel_task_core"
    )
    def test_processing_action_returns_retry_after(
        self,
        mock_core,
    ) -> None:
        key = (
            "mama-sensitive-processing-key-0001"
        )

        reserve_sensitive_action(
            idempotency_key=key,
            owner_id="local-user",
            action_path=(
                "/tasks/task-1/cancel"
            ),
            request_payload={
                "action": "cancel",
                "task_id": "task-1",
            },
        )

        response = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(key),
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
        mock_core.assert_not_called()

    @patch(
        "app.api.tasks._cancel_task_core"
    )
    def test_missing_key_preserves_original_response(
        self,
        mock_core,
    ) -> None:
        mock_core.return_value = {
            "success": True,
            "already_cancelled": False,
        }

        response = self.client.post(
            "/tasks/task-1/cancel",
            headers=self.headers(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertNotIn(
            "Idempotency-Replayed",
            response.headers,
        )
        mock_core.assert_called_once_with(
            "task-1"
        )


if __name__ == "__main__":
    unittest.main()
