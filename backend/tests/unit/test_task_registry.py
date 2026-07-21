import unittest

from app.core.task import TaskRequest, TaskResult, TaskStatus
from app.core.task_registry import TaskRegistry


class TestTaskRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = TaskRegistry()
        self.request = TaskRequest(command="open chrome")

    def test_register_and_get_task(self):
        registered = self.registry.register(self.request)
        stored = self.registry.get(self.request.task_id)

        self.assertEqual(registered.task_id, self.request.task_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, TaskStatus.PENDING)
        self.assertEqual(stored.command, "open chrome")

    def test_duplicate_task_is_rejected(self):
        self.registry.register(self.request)

        with self.assertRaises(ValueError):
            self.registry.register(self.request)

    def test_running_transition(self):
        self.registry.register(self.request)
        record = self.registry.mark_running(self.request.task_id)

        self.assertEqual(record.status, TaskStatus.RUNNING)
        self.assertIsNotNone(record.started_at)

    def test_successful_completion(self):
        self.registry.register(self.request)
        self.registry.mark_running(self.request.task_id)

        result = TaskResult.succeeded(
            task_id=self.request.task_id,
            message="Chrome opened.",
            output={"application": "chrome"},
        )

        record = self.registry.complete(result)

        self.assertEqual(record.status, TaskStatus.SUCCEEDED)
        self.assertEqual(record.message, "Chrome opened.")
        self.assertEqual(
            record.output,
            {"application": "chrome"},
        )
        self.assertIsNotNone(record.finished_at)

    def test_failed_completion(self):
        self.registry.register(self.request)
        self.registry.mark_running(self.request.task_id)

        result = TaskResult.failed(
            task_id=self.request.task_id,
            message="Chrome could not be opened.",
            error="Executable not found",
        )

        record = self.registry.complete(result)

        self.assertEqual(record.status, TaskStatus.FAILED)
        self.assertEqual(record.error, "Executable not found")

    def test_invalid_terminal_transition_is_rejected(self):
        self.registry.register(self.request)
        self.registry.mark_running(self.request.task_id)

        result = TaskResult.succeeded(
            task_id=self.request.task_id,
        )

        self.registry.complete(result)

        with self.assertRaises(ValueError):
            self.registry.mark_running(self.request.task_id)

    def test_filter_by_status(self):
        first = TaskRequest(command="open chrome")
        second = TaskRequest(command="open notepad")

        self.registry.register(first)
        self.registry.register(second)
        self.registry.mark_running(first.task_id)

        running = self.registry.list(status=TaskStatus.RUNNING)
        pending = self.registry.list(status=TaskStatus.PENDING)

        self.assertEqual(len(running), 1)
        self.assertEqual(running[0].task_id, first.task_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].task_id, second.task_id)

    def test_missing_task_returns_none(self):
        self.assertIsNone(self.registry.get("missing-task"))


if __name__ == "__main__":
    unittest.main()