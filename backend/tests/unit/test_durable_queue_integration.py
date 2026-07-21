import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.core.approval_registry import (
    ApprovalRegistry,
)
from app.core.engine import MamaEngine
from app.core.event_bus import EventBus
from app.core.risk_policy import RiskPolicy
from app.core.task import (
    TaskRequest,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.core.task_worker import DurableTaskWorker
from app.database.queue_db import SQLiteTaskQueueStore
from app.database.state_db import SQLiteStateStore


class TestDurableQueueIntegration(unittest.TestCase):

    def setUp(self):
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temp_directory.name)
            / "durable_integration.db"
        )

        self.state_store = SQLiteStateStore(
            self.database_path
        )

        self.queue_store = SQLiteTaskQueueStore(
            self.database_path
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_pending_task_survives_restart_and_executes(self):
        first_registry = TaskRegistry()

        first_registry.enable_persistence(
            self.state_store,
            restore=False,
        )

        request = TaskRequest(
            command="open notepad",
            source="api",
            autonomy_level=2,
        )

        first_registry.register(request)

        self.queue_store.enqueue(
            request.task_id,
            owner_id="local-user",
        )

        restarted_registry = TaskRegistry()

        restarted_registry.enable_persistence(
            self.state_store,
            restore=True,
            recover_interrupted=True,
        )

        restored = restarted_registry.get(
            request.task_id
        )

        self.assertIsNotNone(restored)
        self.assertEqual(
            restored.status,
            TaskStatus.PENDING,
        )

        executor = Mock(
            return_value="Notepad opened."
        )

        engine = MamaEngine(
            executor=executor,
            bus=EventBus(),
            registry=restarted_registry,
            policy=RiskPolicy(),
            approvals=ApprovalRegistry(),
        )

        worker = DurableTaskWorker(
            execution_engine=engine,
            queue_store=self.queue_store,
            worker_id="restart-worker",
        )

        report = worker.process_next()

        completed_task = (
            restarted_registry.get(
                request.task_id
            )
        )

        queue_record = self.queue_store.get(
            request.task_id
        )

        self.assertEqual(
            report.task_status,
            TaskStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            completed_task.status,
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            queue_record["status"],
            "completed",
        )

        executor.assert_called_once_with(
            "open notepad"
        )


if __name__ == "__main__":
    unittest.main()