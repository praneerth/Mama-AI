import unittest

from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskResult,
    TaskStatus,
)


class TestTaskContracts(unittest.TestCase):

    def test_task_request_creation(self):
        task = TaskRequest(
            command="  open chrome  ",
            source="voice",
            autonomy_level=2,
            risk_level=RiskLevel.LOW,
        )

        self.assertEqual(task.command, "open chrome")
        self.assertEqual(task.source, "voice")
        self.assertEqual(task.autonomy_level, 2)
        self.assertTrue(task.task_id)

    def test_empty_command_is_rejected(self):
        with self.assertRaises(ValueError):
            TaskRequest(command="   ")

    def test_invalid_autonomy_level_is_rejected(self):
        with self.assertRaises(ValueError):
            TaskRequest(command="open chrome", autonomy_level=5)

    def test_success_result(self):
        task = TaskRequest(command="open chrome")

        result = TaskResult.succeeded(
            task_id=task.task_id,
            output={"application": "chrome"},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.finished_at)

    def test_failed_result(self):
        task = TaskRequest(command="open missing app")

        result = TaskResult.failed(
            task_id=task.task_id,
            message="Application could not be opened.",
            error="Application not found",
        )

        data = result.to_dict()

        self.assertFalse(result.success)
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["error"], "Application not found")


if __name__ == "__main__":
    unittest.main()