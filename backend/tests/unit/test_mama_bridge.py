import unittest
from unittest.mock import patch

from app.core.mama import run
from app.core.task import TaskResult


class TestMamaBridge(unittest.TestCase):

    @patch("app.core.mama.engine.execute")
    def test_successful_result_uses_legacy_format(self, mock_execute):
        mock_execute.return_value = TaskResult.succeeded(
            task_id="task-123",
            message="Chrome opened successfully.",
            output={"application": "chrome"},
        )

        result = run("open chrome")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["success"])
        self.assertEqual(
            result["response"],
            "Chrome opened successfully.",
        )
        self.assertEqual(result["task"], "open chrome")
        self.assertEqual(
            result["result"],
            {"application": "chrome"},
        )
        self.assertIsNone(result["error"])

    @patch("app.core.mama.engine.execute")
    def test_failed_result_uses_legacy_format(self, mock_execute):
        mock_execute.return_value = TaskResult.failed(
            task_id="task-456",
            message="Application could not be opened.",
            error="Application not found",
        )

        result = run("open missing application")

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["success"])
        self.assertEqual(
            result["error"],
            "Application not found",
        )

    @patch("app.core.mama.engine.execute")
    def test_execution_options_are_forwarded(self, mock_execute):
        mock_execute.return_value = TaskResult.succeeded(
            task_id="task-789",
            message="Task completed.",
        )

        run(
            "open notepad",
            source="voice",
            autonomy_level=2,
        )

        mock_execute.assert_called_once_with(
            "open notepad",
            source="voice",
            autonomy_level=2,
        )


if __name__ == "__main__":
    unittest.main()