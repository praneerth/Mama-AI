import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.chat import ChatRequest, chat
from app.core.engine import engine
from app.core.task import TaskStatus


class TestChatAPI(unittest.TestCase):

    def setUp(self):
        engine.registry.clear()

    def tearDown(self):
        engine.registry.clear()

    @patch("app.api.chat.task_worker.notify")
    @patch("app.api.chat.task_queue_store.enqueue")
    @patch("app.api.chat.process_request")
    def test_automation_returns_queued_task_id(
        self,
        mock_process_request,
        mock_enqueue,
        mock_notify,
    ):
        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }

        mock_enqueue.return_value = {
            "status": "queued",
        }

        response = chat(
            ChatRequest(
                message="open chrome"
            )
        )

        self.assertTrue(response["success"])
        self.assertTrue(response["task_id"])

        self.assertEqual(
            response["task_status"],
            "pending",
        )

        self.assertEqual(
            response["queue_status"],
            "queued",
        )

        record = engine.registry.get(
            response["task_id"]
        )

        self.assertIsNotNone(record)
        self.assertEqual(
            record.status,
            TaskStatus.PENDING,
        )
        self.assertEqual(
            record.command,
            "open chrome",
        )

        mock_enqueue.assert_called_once_with(
            response["task_id"],
            owner_id="local-user",
        )

        mock_notify.assert_called_once_with()

    @patch("app.api.chat.task_queue_store.enqueue")
    @patch("app.api.chat.process_request")
    def test_normal_chat_does_not_use_queue(
        self,
        mock_process_request,
        mock_enqueue,
    ):
        mock_process_request.return_value = {
            "intent": "general_chat",
            "decision": "Hello! How can I help?",
        }

        response = chat(
            ChatRequest(message="hi mama")
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
        self.assertIsNone(
            response["queue_status"]
        )

        mock_enqueue.assert_not_called()

    def test_empty_message_is_rejected(self):
        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(message="   ")
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

    @patch("app.api.chat.task_worker.notify")
    @patch("app.api.chat.task_queue_store.enqueue")
    @patch("app.api.chat.process_request")
    def test_web_search_is_queued(
        self,
        mock_process_request,
        mock_enqueue,
        mock_notify,
    ):
        mock_process_request.return_value = {
            "intent": "web_search",
            "decision": "Search the web",
        }

        mock_enqueue.return_value = {
            "status": "queued",
        }

        response = chat(
            ChatRequest(
                message="search Python tutorials"
            )
        )

        self.assertTrue(response["task_id"])
        self.assertEqual(
            response["intent"],
            "web_search",
        )
        self.assertEqual(
            response["queue_status"],
            "queued",
        )

        mock_notify.assert_called_once_with()

    @patch("app.api.chat.task_queue_store.enqueue")
    @patch("app.api.chat.process_request")
    def test_queue_failure_cancels_task(
        self,
        mock_process_request,
        mock_enqueue,
    ):
        mock_process_request.return_value = {
            "intent": "open_application",
            "decision": "Open Chrome",
        }

        mock_enqueue.side_effect = RuntimeError(
            "Queue unavailable"
        )

        with self.assertRaises(
            HTTPException
        ) as context:
            chat(
                ChatRequest(
                    message="open chrome"
                )
            )

        self.assertEqual(
            context.exception.status_code,
            503,
        )

        records = engine.registry.list()

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].status,
            TaskStatus.CANCELLED,
        )


if __name__ == "__main__":
    unittest.main()