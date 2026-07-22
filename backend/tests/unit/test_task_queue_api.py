import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.tasks import (
    cancel_task,
    get_task_attempts,
    get_task_queue,
    list_failed_queue,
    list_queue,
    retry_task,
)
from app.core.engine import engine
from app.core.task import (
    TaskRequest,
    TaskStatus,
)


class TestTaskQueueAPI(unittest.TestCase):

    def setUp(self):
        engine.registry.clear()

    def tearDown(self):
        engine.registry.clear()

    def create_pending_task(self):
        request = TaskRequest(
            command="open notepad",
            source="api",
            autonomy_level=2,
        )

        engine.registry.register(request)

        return request

    @patch(
        "app.api.tasks.task_queue_store.list"
    )
    def test_list_queue(
        self,
        mock_list,
    ):
        mock_list.return_value = [
            {
                "task_id": "task-1",
                "status": "queued",
            }
        ]

        response = list_queue(
            status="queued",
            owner_id="local-user",
            limit=20,
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["count"],
            1,
        )

        mock_list.assert_called_once_with(
            status="queued",
            owner_id="local-user",
            limit=20,
        )

    @patch(
        "app.api.tasks.task_queue_store.list"
    )
    def test_list_failed_queue(
        self,
        mock_list,
    ):
        mock_list.return_value = [
            {
                "task_id": "task-1",
                "status": "failed",
                "attempts": 3,
                "max_attempts": 3,
            }
        ]

        response = list_failed_queue(
            owner_id="local-user",
            limit=25,
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["count"],
            1,
        )

        self.assertEqual(
            response["queue"][0]["status"],
            "failed",
        )

        mock_list.assert_called_once_with(
            status="failed",
            owner_id="local-user",
            limit=25,
        )

    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_get_task_queue(
        self,
        mock_get,
    ):
        mock_get.return_value = {
            "task_id": "task-1",
            "status": "queued",
        }

        response = get_task_queue(
            "task-1"
        )

        self.assertEqual(
            response["queue"]["status"],
            "queued",
        )

    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_missing_queue_record_returns_404(
        self,
        mock_get,
    ):
        mock_get.return_value = None

        with self.assertRaises(
            HTTPException
        ) as context:
            get_task_queue("missing-task")

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_get_task_attempts(
        self,
        mock_get,
    ):
        request = self.create_pending_task()

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "failed",
            "attempts": 3,
            "max_attempts": 3,
            "available_at": (
                "2026-01-01T00:00:00+00:00"
            ),
            "last_error": "Engine transport failure",
        }

        response = get_task_attempts(
            request.task_id
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["attempts"],
            3,
        )

        self.assertEqual(
            response["remaining_attempts"],
            0,
        )

        self.assertTrue(
            response["attempt_cycle_exhausted"]
        )

        self.assertTrue(
            response["retryable"]
        )

    @patch(
        "app.api.tasks.task_worker.notify"
    )
    @patch(
        "app.api.tasks.task_queue_store.retry_failed"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_retry_failed_pending_task(
        self,
        mock_get,
        mock_retry,
        mock_notify,
    ):
        request = self.create_pending_task()

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "failed",
            "attempts": 3,
            "max_attempts": 3,
        }

        mock_retry.return_value = {
            "task_id": request.task_id,
            "status": "queued",
            "attempts": 0,
            "max_attempts": 4,
        }

        response = retry_task(
            request.task_id,
            max_attempts=4,
            delay_seconds=15,
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["task"]["status"],
            "pending",
        )

        self.assertEqual(
            response["queue"]["status"],
            "queued",
        )

        mock_retry.assert_called_once_with(
            request.task_id,
            max_attempts=4,
            delay_seconds=15,
        )

        mock_notify.assert_called_once_with()

    @patch(
        "app.api.tasks.task_queue_store.retry_failed"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_retry_rejects_non_failed_queue(
        self,
        mock_get,
        mock_retry,
    ):
        request = self.create_pending_task()

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "queued",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            retry_task(
                request.task_id
            )

        self.assertEqual(
            context.exception.status_code,
            409,
        )

        mock_retry.assert_not_called()

    @patch(
        "app.api.tasks.task_queue_store.retry_failed"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_retry_rejects_non_pending_task(
        self,
        mock_get,
        mock_retry,
    ):
        request = self.create_pending_task()

        engine.registry.mark_running(
            request.task_id
        )

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "failed",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            retry_task(
                request.task_id
            )

        self.assertEqual(
            context.exception.status_code,
            409,
        )

        mock_retry.assert_not_called()

    def test_retry_missing_task_returns_404(
        self,
    ):
        with self.assertRaises(
            HTTPException
        ) as context:
            retry_task(
                "missing-task"
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    @patch(
        "app.api.tasks.task_queue_store.retry_failed"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_retry_missing_queue_returns_404(
        self,
        mock_get,
        mock_retry,
    ):
        request = self.create_pending_task()
        mock_get.return_value = None

        with self.assertRaises(
            HTTPException
        ) as context:
            retry_task(
                request.task_id
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

        mock_retry.assert_not_called()

    @patch(
        "app.api.tasks.task_queue_store.cancel_queued"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_cancel_pending_queued_task(
        self,
        mock_get,
        mock_cancel,
    ):
        request = self.create_pending_task()

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "queued",
        }

        mock_cancel.return_value = {
            "task_id": request.task_id,
            "status": "cancelled",
        }

        response = cancel_task(
            request.task_id
        )

        task_record = engine.registry.get(
            request.task_id
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["queue"]["status"],
            "cancelled",
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.CANCELLED,
        )

        mock_cancel.assert_called_once_with(
            request.task_id
        )

    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_running_task_cannot_be_cancelled(
        self,
        mock_get,
    ):
        request = self.create_pending_task()

        engine.registry.mark_running(
            request.task_id
        )

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "claimed",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            cancel_task(request.task_id)

        self.assertEqual(
            context.exception.status_code,
            409,
        )

    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_claimed_queue_task_cannot_be_cancelled(
        self,
        mock_get,
    ):
        request = self.create_pending_task()

        mock_get.return_value = {
            "task_id": request.task_id,
            "status": "claimed",
        }

        with patch(
            "app.api.tasks.task_queue_store.cancel_queued",
            side_effect=ValueError(
                "Task cannot be safely cancelled "
                "from queue status claimed."
            ),
        ):
            with self.assertRaises(
                HTTPException
            ) as context:
                cancel_task(request.task_id)

        self.assertEqual(
            context.exception.status_code,
            409,
        )


if __name__ == "__main__":
    unittest.main()