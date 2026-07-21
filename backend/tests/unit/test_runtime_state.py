import tempfile
import unittest
from pathlib import Path

from app.core.approval_registry import (
    ApprovalRegistry,
)
from app.core.runtime_state import (
    RuntimeStateManager,
)
from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.database.state_db import SQLiteStateStore


class FakeWorker:

    def __init__(
        self,
        events=None,
    ):
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.events = events

    @property
    def running(self):
        return self._running

    def start(self):
        self.start_calls += 1

        if self.events is not None:
            self.events.append(
                "worker_start"
            )

        if self._running:
            return False

        self._running = True
        return True

    def stop(
        self,
        *,
        timeout=5.0,
    ):
        self.stop_calls += 1
        self._running = False

        if self.events is not None:
            self.events.append(
                "worker_stop"
            )

        return True


class FakeReport:

    def __init__(
        self,
        changes=0,
    ):
        self.changes = changes

    def to_dict(self):
        return {
            "changes": self.changes,
            "scanned_tasks": 1,
            "scanned_queue": 1,
        }


class FakeReconciler:

    def __init__(
        self,
        events=None,
        *,
        changes=0,
        error=None,
    ):
        self.calls = 0
        self.events = events
        self.changes = changes
        self.error = error

    def reconcile(self):
        self.calls += 1

        if self.events is not None:
            self.events.append(
                "reconcile"
            )

        if self.error is not None:
            raise self.error

        return FakeReport(
            changes=self.changes
        )


class TestRuntimeStateManager(unittest.TestCase):

    def setUp(self):
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temp_directory.name)
            / "runtime_state_test.db"
        )

        self.store = SQLiteStateStore(
            self.database_path
        )

        self.tasks = TaskRegistry()
        self.approvals = ApprovalRegistry()

        self.manager = RuntimeStateManager(
            tasks=self.tasks,
            approvals=self.approvals,
            store=self.store,
        )

    def tearDown(self):
        self.manager.stop()
        self.temp_directory.cleanup()

    def test_start_enables_both_registries(self):
        summary = self.manager.start()

        self.assertTrue(
            summary["started"]
        )

        self.assertFalse(
            summary["already_started"]
        )

        self.assertTrue(
            self.tasks.persistence_enabled
        )

        self.assertTrue(
            self.approvals.persistence_enabled
        )

        self.assertTrue(
            self.manager.started
        )

    def test_start_is_idempotent(self):
        first = self.manager.start()
        second = self.manager.start()

        self.assertFalse(
            first["already_started"]
        )

        self.assertTrue(
            second["already_started"]
        )

    def test_task_and_approval_survive_restart(self):
        self.manager.start(
            recover_interrupted=False
        )

        request = TaskRequest(
            command=(
                "delete the file report.pdf"
            ),
            risk_level=RiskLevel.HIGH,
        )

        self.tasks.register(request)

        self.tasks.mark_waiting_approval(
            request.task_id
        )

        approval = self.approvals.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
        )

        self.manager.stop()

        restored_tasks = TaskRegistry()
        restored_approvals = ApprovalRegistry()

        restarted = RuntimeStateManager(
            tasks=restored_tasks,
            approvals=restored_approvals,
            store=self.store,
        )

        summary = restarted.start(
            recover_interrupted=False
        )

        self.assertEqual(
            summary["restored_tasks"],
            1,
        )

        self.assertEqual(
            summary["restored_approvals"],
            1,
        )

        restored_task = (
            restored_tasks.get(
                request.task_id
            )
        )

        restored_approval = (
            restored_approvals.get(
                approval.approval_id
            )
        )

        self.assertIsNotNone(
            restored_task
        )

        self.assertIsNotNone(
            restored_approval
        )

        self.assertEqual(
            restored_task.status,
            TaskStatus.WAITING_APPROVAL,
        )

        restarted.stop()

    def test_interrupted_running_task_becomes_failed(
        self,
    ):
        self.manager.start(
            recover_interrupted=False
        )

        request = TaskRequest(
            command=(
                "perform background task"
            )
        )

        self.tasks.register(request)

        self.tasks.mark_running(
            request.task_id
        )

        self.manager.stop()

        restored_tasks = TaskRegistry()
        restored_approvals = ApprovalRegistry()

        restarted = RuntimeStateManager(
            tasks=restored_tasks,
            approvals=restored_approvals,
            store=self.store,
        )

        restarted.start(
            recover_interrupted=True
        )

        restored = restored_tasks.get(
            request.task_id
        )

        self.assertIsNotNone(restored)

        self.assertEqual(
            restored.status,
            TaskStatus.FAILED,
        )

        self.assertIn(
            "restart",
            restored.error.lower(),
        )

        restarted.stop()

    def test_pending_task_remains_pending_after_restart(
        self,
    ):
        self.manager.start(
            recover_interrupted=False
        )

        request = TaskRequest(
            command="open notepad"
        )

        self.tasks.register(request)
        self.manager.stop()

        restored_tasks = TaskRegistry()
        restored_approvals = ApprovalRegistry()

        restarted = RuntimeStateManager(
            tasks=restored_tasks,
            approvals=restored_approvals,
            store=self.store,
        )

        restarted.start(
            recover_interrupted=True
        )

        restored = restored_tasks.get(
            request.task_id
        )

        self.assertIsNotNone(restored)

        self.assertEqual(
            restored.status,
            TaskStatus.PENDING,
        )

        restarted.stop()

    def test_stop_disables_persistence(self):
        self.manager.start()

        summary = self.manager.stop()

        self.assertTrue(
            summary["stopped"]
        )

        self.assertFalse(
            summary["already_stopped"]
        )

        self.assertFalse(
            self.tasks.persistence_enabled
        )

        self.assertFalse(
            self.approvals.persistence_enabled
        )

        self.assertFalse(
            self.manager.started
        )

    def test_worker_lifecycle_is_managed(self):
        worker = FakeWorker()

        manager = RuntimeStateManager(
            tasks=TaskRegistry(),
            approvals=ApprovalRegistry(),
            store=self.store,
            worker=worker,
        )

        started = manager.start()

        self.assertTrue(
            started["worker_started"]
        )

        self.assertTrue(
            started["worker_running"]
        )

        self.assertEqual(
            worker.start_calls,
            1,
        )

        stopped = manager.stop()

        self.assertTrue(
            stopped["worker_stopped"]
        )

        self.assertEqual(
            worker.stop_calls,
            1,
        )

        self.assertFalse(
            worker.running
        )

    def test_reconciliation_runs_before_worker(
        self,
    ):
        events = []

        reconciler = FakeReconciler(
            events,
            changes=2,
        )

        worker = FakeWorker(events)

        manager = RuntimeStateManager(
            tasks=TaskRegistry(),
            approvals=ApprovalRegistry(),
            store=self.store,
            worker=worker,
            reconciler=reconciler,
        )

        summary = manager.start()

        self.assertEqual(
            events,
            [
                "reconcile",
                "worker_start",
            ],
        )

        self.assertEqual(
            reconciler.calls,
            1,
        )

        self.assertEqual(
            summary["reconciliation"][
                "changes"
            ],
            2,
        )

        manager.stop()

    def test_reconciliation_is_not_repeated_on_idempotent_start(
        self,
    ):
        reconciler = FakeReconciler()

        manager = RuntimeStateManager(
            tasks=TaskRegistry(),
            approvals=ApprovalRegistry(),
            store=self.store,
            reconciler=reconciler,
        )

        first = manager.start()
        second = manager.start()

        self.assertEqual(
            reconciler.calls,
            1,
        )

        self.assertFalse(
            first["already_started"]
        )

        self.assertTrue(
            second["already_started"]
        )

        manager.stop()

    def test_reconciliation_failure_prevents_worker_start(
        self,
    ):
        worker = FakeWorker()

        reconciler = FakeReconciler(
            error=RuntimeError(
                "Reconciliation failed"
            )
        )

        tasks = TaskRegistry()
        approvals = ApprovalRegistry()

        manager = RuntimeStateManager(
            tasks=tasks,
            approvals=approvals,
            store=self.store,
            worker=worker,
            reconciler=reconciler,
        )

        with self.assertRaises(
            RuntimeError
        ):
            manager.start()

        self.assertEqual(
            worker.start_calls,
            0,
        )

        self.assertFalse(
            worker.running
        )

        self.assertFalse(
            tasks.persistence_enabled
        )

        self.assertFalse(
            approvals.persistence_enabled
        )

        self.assertFalse(
            manager.started
        )


if __name__ == "__main__":
    unittest.main()