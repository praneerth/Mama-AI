import tempfile
import unittest
from pathlib import Path

from app.core.queue_reconciler import (
    QueueReconciler,
)
from app.core.task import (
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.database.queue_db import (
    SQLiteTaskQueueStore,
)


class TestQueueReconciler(unittest.TestCase):

    def setUp(self):
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temp_directory.name)
            / "reconciliation_test.db"
        )

        self.registry = TaskRegistry()

        self.queue = SQLiteTaskQueueStore(
            self.database_path
        )

        self.reconciler = QueueReconciler(
            tasks=self.registry,
            queue=self.queue,
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def create_task(
        self,
        command="open notepad",
    ):
        request = TaskRequest(
            command=command,
            source="api",
            autonomy_level=2,
        )

        self.registry.register(request)

        return request

    def test_pending_task_without_queue_is_enqueued(self):
        request = self.create_task()

        report = self.reconciler.reconcile()

        queue_record = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.enqueued_missing,
            1,
        )

        self.assertIsNotNone(queue_record)

        self.assertEqual(
            queue_record["status"],
            "queued",
        )

    def test_reconciliation_is_idempotent(self):
        self.create_task()

        first = self.reconciler.reconcile()
        second = self.reconciler.reconcile()

        self.assertEqual(
            first.changes,
            1,
        )

        self.assertEqual(
            second.changes,
            0,
        )

    def test_orphan_queued_job_is_cancelled(self):
        self.queue.enqueue(
            "orphan-task"
        )

        report = self.reconciler.reconcile()

        stored = self.queue.get(
            "orphan-task"
        )

        self.assertEqual(
            report.cancelled_orphan_jobs,
            1,
        )

        self.assertEqual(
            stored["status"],
            "cancelled",
        )

    def test_terminal_task_queue_job_is_cancelled(self):
        request = self.create_task()

        self.registry.mark_running(
            request.task_id
        )

        self.registry.complete(
            TaskResult.succeeded(
                task_id=request.task_id,
                message="Task completed.",
            )
        )

        self.queue.enqueue(
            request.task_id
        )

        report = self.reconciler.reconcile()

        stored = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.cancelled_non_executable_jobs,
            1,
        )

        self.assertEqual(
            stored["status"],
            "cancelled",
        )

    def test_waiting_approval_job_is_not_executed_again(self):
        request = self.create_task(
            "delete report.pdf"
        )

        self.registry.mark_waiting_approval(
            request.task_id
        )

        self.queue.enqueue(
            request.task_id
        )

        report = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        queue_record = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.cancelled_non_executable_jobs,
            1,
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.WAITING_APPROVAL,
        )

        self.assertEqual(
            queue_record["status"],
            "cancelled",
        )

    def test_stale_claimed_job_is_requeued(self):
        request = self.create_task()

        self.queue.enqueue(
            request.task_id,
            max_attempts=3,
        )

        self.queue.claim_next(
            worker_id="stale-worker",
        )

        report = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        queue_record = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.requeued_claimed,
            1,
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.PENDING,
        )

        self.assertEqual(
            queue_record["status"],
            "queued",
        )

        self.assertIsNone(
            queue_record["worker_id"]
        )

    def test_exhausted_claim_is_preserved_for_retry(self):
        request = self.create_task()

        self.queue.enqueue(
            request.task_id,
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="stale-worker",
        )

        report = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        queue_record = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.preserved_failed_jobs,
            1,
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.PENDING,
        )

        self.assertEqual(
            queue_record["status"],
            "failed",
        )

        self.assertIsNone(
            queue_record["worker_id"]
        )

    def test_pending_task_with_completed_queue_is_cancelled(self):
        request = self.create_task()

        self.queue.enqueue(
            request.task_id
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        self.queue.complete(
            request.task_id,
            worker_id="worker-1",
        )

        report = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        self.assertEqual(
            report.cancelled_inconsistent_tasks,
            1,
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.CANCELLED,
        )

    def test_pending_task_with_failed_queue_is_preserved(self):
        request = self.create_task()

        self.queue.enqueue(
            request.task_id,
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        self.queue.fail(
            request.task_id,
            worker_id="worker-1",
            error="Engine transport failed",
        )

        first = self.reconciler.reconcile()
        second = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        queue_record = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            first.preserved_failed_jobs,
            1,
        )

        self.assertEqual(
            second.preserved_failed_jobs,
            1,
        )

        self.assertEqual(
            first.changes,
            0,
        )

        self.assertEqual(
            second.changes,
            0,
        )

        self.assertEqual(
            task_record.status,
            TaskStatus.PENDING,
        )

        self.assertEqual(
            queue_record["status"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()