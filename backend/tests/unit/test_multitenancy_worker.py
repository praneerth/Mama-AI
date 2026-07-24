import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.core.engine import MamaEngine
from app.core.task import TaskRequest
from app.core.task_registry import TaskRegistry
from app.core.task_worker import DurableTaskWorker
from app.database.queue_db import SQLiteTaskQueueStore


class TestMultiUserWorkerOwnership(unittest.TestCase):
    def test_explicit_owner_mismatch_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = TaskRegistry()
            request = TaskRequest(
                command="open notepad",
                metadata={"owner_id": "user-1"},
            )
            registry.register(request)
            queue = SQLiteTaskQueueStore(Path(directory) / "queue.db")
            queue.enqueue(request.task_id, owner_id="user-2", max_attempts=1)
            executor = Mock(return_value={"message": "done"})
            engine = MamaEngine(registry=registry, executor=executor)
            worker = DurableTaskWorker(
                execution_engine=engine,
                queue_store=queue,
                worker_id="worker-1",
                retry_delay_seconds=0,
            )

            report = worker.process_next()

            self.assertEqual(report.queue_status, "failed")
            self.assertIn("owner", report.error.lower())
            executor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
