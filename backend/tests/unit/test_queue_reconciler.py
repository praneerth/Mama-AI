import sqlite3
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

    def reconciliation_events(
        self,
        task_id,
    ):
        return list(
            reversed(
                self.queue.audit_store.list(
                    task_id=task_id,
                    event_type="reconciled",
                    limit=100,
                )
            )
        )

    def latest_reconciliation(
        self,
        task_id,
    ):
        events = self.reconciliation_events(
            task_id
        )

        self.assertTrue(events)
        return events[-1]

    def test_pending_task_without_queue_is_enqueued(self):
        request = self.create_task()

        report = self.reconciler.reconcile()

        queue_record = self.queue.get(
            request.task_id
        )

        event = self.latest_reconciliation(
            request.task_id
        )

        self.assertEqual(
            report.enqueued_missing,
            1,
        )

        self.assertEqual(
            report.recorded_audit_events,
            1,
        )

        self.assertIsNotNone(queue_record)

        self.assertEqual(
            queue_record["status"],
            "queued",
        )

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "enqueued_missing_queue",
        )

    def test_reconciliation_is_idempotent(self):
        request = self.create_task()

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

        self.assertEqual(
            len(
                self.reconciliation_events(
                    request.task_id
                )
            ),
            1,
        )

    def test_orphan_queued_job_is_cancelled(self):
        self.queue.enqueue(
            "orphan-task"
        )

        report = self.reconciler.reconcile()

        stored = self.queue.get(
            "orphan-task"
        )

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "cancelled_orphan_queue_job",
        )

    def test_orphan_failed_job_is_preserved_once(self):
        self.queue.enqueue(
            "orphan-task",
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        self.queue.fail(
            "orphan-task",
            worker_id="worker-1",
            error="Delivery failed",
        )

        first = self.reconciler.reconcile()
        second = self.reconciler.reconcile()

        self.assertEqual(
            first.preserved_failed_jobs,
            1,
        )

        self.assertEqual(
            second.preserved_failed_jobs,
            1,
        )

        self.assertEqual(
            first.recorded_audit_events,
            1,
        )

        self.assertEqual(
            second.recorded_audit_events,
            0,
        )

        self.assertEqual(
            len(
                self.reconciliation_events(
                    "orphan-task"
                )
            ),
            1,
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

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "cancelled_non_executable_queue_job",
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

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["metadata"]["task_status"],
            "waiting_approval",
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

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["queue_status"],
            "queued",
        )

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "recovered_claimed_queue_job",
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

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["queue_status"],
            "failed",
        )

    def test_claim_without_worker_is_cancelled(self):
        request = self.create_task()

        self.queue.enqueue(
            request.task_id
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        with sqlite3.connect(
            self.database_path
        ) as connection:
            connection.execute(
                """
                UPDATE task_queue
                SET worker_id = NULL
                WHERE task_id = ?
                """,
                (request.task_id,),
            )

        report = self.reconciler.reconcile()

        task_record = self.registry.get(
            request.task_id
        )

        queue_record = self.queue.get(
            request.task_id
        )

        event = self.latest_reconciliation(
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

        self.assertEqual(
            queue_record["status"],
            "cancelled",
        )

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "cancelled_claim_without_worker",
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

        event = self.latest_reconciliation(
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

        self.assertEqual(
            event["metadata"][
                "reconciliation_action"
            ],
            "cancelled_task_for_terminal_queue",
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
            first.recorded_audit_events,
            1,
        )

        self.assertEqual(
            second.recorded_audit_events,
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

        self.assertEqual(
            len(
                self.reconciliation_events(
                    request.task_id
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()