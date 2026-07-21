import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from app.api.chat import ChatRequest, chat
from app.core.engine import engine
from app.core.task import TaskStatus


class TestChatAPI(unittest.TestCase):

    def setUp(self):
        engine.registry.clear()

    def tearDown(self):
        engine.registry.clear()

    @patch("app.api.chat.process_request")
    def test_automation_returns_pending_task_id(
        self,
        mock_process_request,
    ):
        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }

        background_tasks = BackgroundTasks()

        response = chat(
            ChatRequest(message="open chrome"),
            background_tasks,
        )

        self.assertTrue(response["success"])
        self.assertTrue(response["task_id"])
        self.assertEqual(
            response["task_status"],
            "pending",
        )
        self.assertEqual(len(background_tasks.tasks), 1)

        record = engine.registry.get(response["task_id"])

        self.assertIsNotNone(record)
        self.assertEqual(
            record.status,
            TaskStatus.PENDING,
        )
        self.assertEqual(
            record.command,
            "open chrome",
        )

    @patch("app.api.chat.process_request")
    def test_normal_chat_returns_completed_response(
        self,
        mock_process_request,
    ):
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello! How can I help?",
        }

        background_tasks = BackgroundTasks()

        response = chat(
            ChatRequest(message="hi mama"),
            background_tasks,
        )

        self.assertEqual(
            response["response"],
            "Hello! How can I help?",
        )
        self.assertIsNone(response["task_id"])
        self.assertEqual(
            response["task_status"],
            "completed",
        )
        self.assertEqual(len(background_tasks.tasks), 0)

    def test_empty_message_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            chat(
                ChatRequest(message="   "),
                BackgroundTasks(),
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

    @patch("app.api.chat.process_request")
    def test_web_search_creates_background_task(
        self,
        mock_process_request,
    ):
        mock_process_request.return_value = {
            "intent": "web_search",
            "decision": "Search the web",
        }

        response = chat(
            ChatRequest(message="search Python tutorials"),
            BackgroundTasks(),
        )

        self.assertTrue(response["task_id"])
        self.assertEqual(
            response["intent"],
            "web_search",
        )


if __name__ == "__main__":
    unittest.main()