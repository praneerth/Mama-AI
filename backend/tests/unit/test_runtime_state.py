import tempfile
import unittest
from pathlib import Path

from app.core.approval_registry import (
    ApprovalRegistry,
)
from app.core.runtime_state import RuntimeStateManager
from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.database.state_db import SQLiteStateStore


class TestRuntimeStateManager(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

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

        self.assertTrue(summary["started"])
        self.assertFalse(summary["already_started"])
        self.assertTrue(
            self.tasks.persistence_enabled
        )
        self.assertTrue(
            self.approvals.persistence_enabled
        )
        self.assertTrue(self.manager.started)

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
            command="delete the file report.pdf",
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
            reasons=[
                "File deletion requires approval."
            ],
        )

        self.manager.stop()

        restored_tasks = TaskRegistry()
        restored_approvals = ApprovalRegistry()

        restarted_manager = RuntimeStateManager(
            tasks=restored_tasks,
            approvals=restored_approvals,
            store=self.store,
        )

        summary = restarted_manager.start(
            recover_interrupted=False
        )

        restored_task = restored_tasks.get(
            request.task_id
        )

        restored_approval = restored_approvals.get(
            approval.approval_id
        )

        self.assertEqual(
            summary["restored_tasks"],
            1,
        )
        self.assertEqual(
            summary["restored_approvals"],
            1,
        )
        self.assertIsNotNone(restored_task)
        self.assertIsNotNone(restored_approval)
        self.assertEqual(
            restored_task.status,
            TaskStatus.WAITING_APPROVAL,
        )

        restarted_manager.stop()

    def test_interrupted_running_task_becomes_failed(self):
        self.manager.start(
            recover_interrupted=False
        )

        request = TaskRequest(
            command="perform background task"
        )

        self.tasks.register(request)
        self.tasks.mark_running(
            request.task_id
        )

        self.manager.stop()

        restored_tasks = TaskRegistry()
        restored_approvals = ApprovalRegistry()

        restarted_manager = RuntimeStateManager(
            tasks=restored_tasks,
            approvals=restored_approvals,
            store=self.store,
        )

        restarted_manager.start(
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

        restarted_manager.stop()

    def test_stop_disables_persistence(self):
        self.manager.start()
        summary = self.manager.stop()

        self.assertTrue(summary["stopped"])
        self.assertFalse(
            summary["already_stopped"]
        )
        self.assertFalse(
            self.tasks.persistence_enabled
        )
        self.assertFalse(
            self.approvals.persistence_enabled
        )
        self.assertFalse(self.manager.started)


if __name__ == "__main__":
    unittest.main()