import unittest

from app.core.engine import MamaEngine
from app.core.task import TaskRequest, TaskStatus


class TestMamaEngine(unittest.TestCase):

    def test_successful_execution(self):
        engine = MamaEngine(
            executor=lambda command: {
                "response": f"Executed: {command}"
            }
        )

        result = engine.execute("open chrome")

        self.assertTrue(result.success)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.message, "Executed: open chrome")
        self.assertEqual(
            result.output,
            {"response": "Executed: open chrome"},
        )

    def test_task_request_is_supported(self):
        request = TaskRequest(
            command="open notepad",
            source="voice",
            autonomy_level=2,
        )

        engine = MamaEngine(executor=lambda command: "Done")
        result = engine.execute(request)

        self.assertEqual(result.task_id, request.task_id)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Done")

    def test_empty_task_fails_safely(self):
        engine = MamaEngine(executor=lambda command: "Done")

        result = engine.execute("   ")

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("empty", result.error.lower())

    def test_executor_exception_is_captured(self):
        def failing_executor(command):
            raise RuntimeError("Executor unavailable")

        engine = MamaEngine(executor=failing_executor)
        result = engine.execute("open chrome")

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error, "Executor unavailable")


if __name__ == "__main__":
    unittest.main()