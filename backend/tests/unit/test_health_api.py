import json
import unittest
from unittest.mock import patch

from fastapi.responses import JSONResponse

from app.api.health import (
    health,
    queue_health,
    readiness,
    runtime_health,
)


HEALTHY_DATABASE = {
    "available": True,
    "path": "test.db",
    "error": None,
}


HEALTHY_QUEUE = {
    "available": True,
    "total": 1,
    "counts": {
        "cancelled": 0,
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "queued": 1,
    },
    "stale_claimed": 0,
    "stale_task_ids": [],
    "scan_limit": 1000,
    "possibly_truncated": False,
    "error": None,
}


class TestHealthAPI(unittest.TestCase):

    def test_basic_health(self):
        response = health()

        self.assertEqual(
            response["status"],
            "healthy",
        )

        self.assertTrue(
            response["app"]
        )

        self.assertTrue(
            response["version"]
        )

    @patch(
        "app.api.health.approval_registry"
    )
    @patch(
        "app.api.health.task_registry"
    )
    @patch(
        "app.api.health.task_worker"
    )
    @patch(
        "app.api.health.runtime_state"
    )
    @patch(
        "app.api.health._queue_status"
    )
    @patch(
        "app.api.health._database_status"
    )
    def test_ready_when_all_components_are_running(
        self,
        mock_database,
        mock_queue,
        mock_runtime,
        mock_worker,
        mock_tasks,
        mock_approvals,
    ):
        mock_database.return_value = (
            HEALTHY_DATABASE
        )

        mock_queue.return_value = (
            HEALTHY_QUEUE
        )

        mock_runtime.started = True
        mock_runtime.last_reconciliation = {
            "changes": 0,
        }

        mock_worker.running = True
        mock_worker.worker_id = (
            "test-worker"
        )

        mock_tasks.persistence_enabled = True

        mock_approvals.persistence_enabled = (
            True
        )

        response = readiness()

        self.assertIsInstance(
            response,
            dict,
        )

        self.assertTrue(
            response["ready"]
        )

        self.assertEqual(
            response["status"],
            "ready",
        )

    @patch(
        "app.api.health.approval_registry"
    )
    @patch(
        "app.api.health.task_registry"
    )
    @patch(
        "app.api.health.task_worker"
    )
    @patch(
        "app.api.health.runtime_state"
    )
    @patch(
        "app.api.health._queue_status"
    )
    @patch(
        "app.api.health._database_status"
    )
    def test_not_ready_returns_503(
        self,
        mock_database,
        mock_queue,
        mock_runtime,
        mock_worker,
        mock_tasks,
        mock_approvals,
    ):
        mock_database.return_value = (
            HEALTHY_DATABASE
        )

        mock_queue.return_value = (
            HEALTHY_QUEUE
        )

        mock_runtime.started = False
        mock_worker.running = False
        mock_worker.worker_id = (
            "test-worker"
        )

        mock_tasks.persistence_enabled = False

        mock_approvals.persistence_enabled = (
            False
        )

        response = readiness()

        self.assertIsInstance(
            response,
            JSONResponse,
        )

        self.assertEqual(
            response.status_code,
            503,
        )

        payload = json.loads(
            response.body
        )

        self.assertFalse(
            payload["ready"]
        )

        self.assertEqual(
            payload["status"],
            "not_ready",
        )

    @patch(
        "app.api.health.task_worker"
    )
    @patch(
        "app.api.health.approval_registry"
    )
    @patch(
        "app.api.health.task_registry"
    )
    @patch(
        "app.api.health.runtime_state"
    )
    def test_runtime_health(
        self,
        mock_runtime,
        mock_tasks,
        mock_approvals,
        mock_worker,
    ):
        mock_runtime.started = True

        mock_runtime.last_reconciliation = {
            "changes": 2,
        }

        mock_tasks.persistence_enabled = True

        mock_approvals.persistence_enabled = (
            True
        )

        mock_worker.running = True
        mock_worker.worker_id = (
            "runtime-worker"
        )

        response = runtime_health()

        self.assertEqual(
            response["status"],
            "healthy",
        )

        self.assertEqual(
            response["last_reconciliation"][
                "changes"
            ],
            2,
        )

    @patch(
        "app.api.health._queue_status"
    )
    def test_stale_claimed_job_degrades_queue(
        self,
        mock_queue,
    ):
        queue_status = dict(
            HEALTHY_QUEUE
        )

        queue_status["stale_claimed"] = 1

        queue_status["stale_task_ids"] = [
            "task-1"
        ]

        mock_queue.return_value = (
            queue_status
        )

        response = queue_health()

        self.assertEqual(
            response["status"],
            "degraded",
        )

        self.assertEqual(
            response["stale_claimed"],
            1,
        )


if __name__ == "__main__":
    unittest.main()