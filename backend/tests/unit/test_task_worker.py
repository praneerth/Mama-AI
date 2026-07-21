import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.core.approval_registry import ApprovalRegistry
from app.core.engine import MamaEngine
from app.core.event_bus import EventBus
from app.core.risk_policy import RiskPolicy
from app.core.task import (
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.core.task_worker import DurableTaskWorker
from app.database.queue_db import SQLiteTaskQueueStore


class RaisingEngine:

    def __init__(self, registry):
        self.registry = registry

    def execute(self, task, **options):
        raise RuntimeError("Engine transport failure")


class TestDurableTaskWorker(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp_directory.name)
            / "worker_test.db"
        )

        self.queue = SQLiteTaskQueueStore(
            self.database_path
        )

        self.registry = TaskRegistry()
        self.approvals = ApprovalRegistry()
        self.executor = Mock(
            return_value="Task completed."
        )

        self.engine = MamaEngine(
            executor=self.executor,
            bus=EventBus(),
            registry=self.registry,
            policy=RiskPolicy(),
            approvals=self.approvals,
        )

        self.worker = DurableTaskWorker(
            execution_engine=self.engine,
            queue_store=self.queue,
            worker_id="test-worker",
            lease_seconds=30,
            retry_delay_seconds=0,
            poll_interval=0.05,
        )

    def tearDown(self):
        self.worker.stop(timeout=2)
        self.temp_directory.cleanup()

    def create_queued_task(
        self,
        command="open notepad",
    ):
        request = TaskRequest(
            command=command,
            source="api",
            autonomy_level=2,
            metadata={
                "owner_id": "user-1",
            },
        )

        self.registry.register(request)

        self.queue.enqueue(
            request.task_id,
            owner_id="user-1",
        )

        return request

    def test_empty_queue_returns_none(self):
        self.assertIsNone(
            self.worker.process_next()
        )

    def test_successful_task_is_delivered(self):
        request = self.create_queued_task()

        report = self.worker.process_next()

        stored_task = self.registry.get(
            request.task_id
        )

        stored_queue = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.queue_status,
            "completed",
        )
        self.assertEqual(
            report.task_status,
            TaskStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            stored_task.status,
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            stored_queue["status"],
            "completed",
        )

        self.executor.assert_called_once_with(
            "open notepad"
        )

    def test_high_risk_task_waits_for_approval(self):
        request = self.create_queued_task(
            "delete the file report.pdf"
        )

        report = self.worker.process_next()

        stored_task = self.registry.get(
            request.task_id
        )

        stored_queue = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.task_status,
            TaskStatus.WAITING_APPROVAL.value,
        )
        self.assertEqual(
            stored_task.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertEqual(
            stored_queue["status"],
            "completed",
        )

        self.executor.assert_not_called()

    def test_missing_task_record_is_requeued(self):
        self.queue.enqueue(
            "missing-task",
            owner_id="user-1",
            max_attempts=2,
        )

        report = self.worker.process_next()

        stored_queue = self.queue.get(
            "missing-task"
        )

        self.assertEqual(
            report.queue_status,
            "queued",
        )
        self.assertEqual(
            stored_queue["attempts"],
            1,
        )
        self.assertIn(
            "not found",
            report.error.lower(),
        )

    def test_cancelled_task_is_not_executed(self):
        request = self.create_queued_task()

        self.registry.cancel(
            request.task_id
        )

        report = self.worker.process_next()

        stored_queue = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.queue_status,
            "cancelled",
        )
        self.assertEqual(
            stored_queue["status"],
            "cancelled",
        )

        self.executor.assert_not_called()

    def test_terminal_task_is_not_executed_twice(self):
        request = TaskRequest(
            command="open calculator"
        )

        self.registry.register(request)
        self.registry.mark_running(
            request.task_id
        )

        result = TaskResult.succeeded(
            task_id=request.task_id,
            message="Calculator opened.",
        )

        self.registry.complete(result)

        self.queue.enqueue(
            request.task_id,
            owner_id="user-1",
        )

        report = self.worker.process_next()

        self.assertEqual(
            report.queue_status,
            "completed",
        )
        self.assertEqual(
            report.task_status,
            TaskStatus.SUCCEEDED.value,
        )

        self.executor.assert_not_called()

    def test_unexpected_engine_failure_requeues_job(self):
        request = TaskRequest(
            command="open notepad"
        )

        self.registry.register(request)

        self.queue.enqueue(
            request.task_id,
            owner_id="user-1",
            max_attempts=2,
        )

        failing_worker = DurableTaskWorker(
            execution_engine=RaisingEngine(
                self.registry
            ),
            queue_store=self.queue,
            worker_id="failing-worker",
            retry_delay_seconds=0,
        )

        report = failing_worker.process_next()

        stored_queue = self.queue.get(
            request.task_id
        )

        self.assertEqual(
            report.queue_status,
            "queued",
        )
        self.assertEqual(
            stored_queue["attempts"],
            1,
        )
        self.assertEqual(
            report.error,
            "Engine transport failure",
        )

    def test_background_thread_processes_task(self):
        request = self.create_queued_task()

        started = self.worker.start()
        self.worker.notify()

        deadline = time.monotonic() + 2.0

        while time.monotonic() < deadline:
            queue_record = self.queue.get(
                request.task_id
            )

            if queue_record["status"] == "completed":
                break

            time.sleep(0.02)

        stopped = self.worker.stop(timeout=2)

        stored_task = self.registry.get(
            request.task_id
        )

        stored_queue = self.queue.get(
            request.task_id
        )

        self.assertTrue(started)
        self.assertTrue(stopped)
        self.assertEqual(
            stored_queue["status"],
            "completed",
        )
        self.assertEqual(
            stored_task.status,
            TaskStatus.SUCCEEDED,
        )


if __name__ == "__main__":
    unittest.main()