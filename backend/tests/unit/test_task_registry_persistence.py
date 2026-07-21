import tempfile
import unittest
from pathlib import Path

from app.core.task import (
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.database.state_db import SQLiteStateStore


class TestTaskRegistryPersistence(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp_directory.name)
            / "task_registry_test.db"
        )

        self.store = SQLiteStateStore(
            self.database_path
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_persistence_is_disabled_by_default(self):
        registry = TaskRegistry()
        request = TaskRequest(command="open notepad")

        registry.register(request)

        self.assertFalse(
            registry.persistence_enabled
        )
        self.assertIsNone(
            self.store.get_task(request.task_id)
        )

    def test_registered_task_is_persisted(self):
        registry = TaskRegistry()

        registry.enable_persistence(
            self.store,
            restore=False,
        )

        request = TaskRequest(command="open notepad")
        registry.register(request)

        stored = self.store.get_task(
            request.task_id
        )

        self.assertIsNotNone(stored)
        self.assertEqual(
            stored["status"],
            TaskStatus.PENDING.value,
        )
        self.assertEqual(
            stored["command"],
            "open notepad",
        )

    def test_completed_task_restores_in_new_registry(self):
        first_registry = TaskRegistry()

        first_registry.enable_persistence(
            self.store,
            restore=False,
        )

        request = TaskRequest(
            command="open calculator"
        )

        first_registry.register(request)
        first_registry.mark_running(request.task_id)

        result = TaskResult.succeeded(
            task_id=request.task_id,
            message="Calculator opened.",
            output={
                "application": "calculator",
            },
        )

        first_registry.complete(result)

        second_registry = TaskRegistry()

        restored_count = second_registry.enable_persistence(
            self.store,
            restore=True,
            recover_interrupted=False,
        )

        restored = second_registry.get(
            request.task_id
        )

        self.assertEqual(restored_count, 1)
        self.assertIsNotNone(restored)
        self.assertEqual(
            restored.status,
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            restored.output,
            {"application": "calculator"},
        )

    def test_clear_only_removes_memory(self):
        registry = TaskRegistry()

        registry.enable_persistence(
            self.store,
            restore=False,
        )

        request = TaskRequest(command="open notepad")
        registry.register(request)

        registry.clear()

        self.assertEqual(registry.count(), 0)
        self.assertIsNotNone(
            self.store.get_task(request.task_id)
        )

    def test_interrupted_task_is_recovered_as_failed(self):
        first_registry = TaskRegistry()

        first_registry.enable_persistence(
            self.store,
            restore=False,
        )

        request = TaskRequest(
            command="perform background task"
        )

        first_registry.register(request)
        first_registry.mark_running(request.task_id)

        second_registry = TaskRegistry()

        second_registry.enable_persistence(
            self.store,
            restore=True,
            recover_interrupted=True,
        )

        restored = second_registry.get(
            request.task_id
        )

        stored = self.store.get_task(
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
        self.assertEqual(
            stored["status"],
            TaskStatus.FAILED.value,
        )


if __name__ == "__main__":
    unittest.main()