import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.history import (
    get_attempt_audit,
    history,
    list_attempt_audits,
)
from app.api.tasks import (
    get_task_history,
)
from app.core.engine import engine
from app.core.task import TaskRequest


class TestAttemptHistoryAPI(
    unittest.TestCase
):

    def setUp(self) -> None:
        engine.registry.clear()

    def tearDown(self) -> None:
        engine.registry.clear()

    def create_pending_task(
        self,
    ) -> TaskRequest:
        request = TaskRequest(
            command="open notepad",
            source="api",
            autonomy_level=2,
        )

        engine.registry.register(
            request
        )

        return request

    @patch(
        "app.api.history.get_history"
    )
    def test_legacy_history_is_preserved(
        self,
        mock_get_history,
    ) -> None:
        mock_get_history.return_value = [
            {
                "task": "open notepad",
                "success": True,
            }
        ]

        response = history()

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            len(response["history"]),
            1,
        )

        mock_get_history.assert_called_once_with()

    @patch(
        "app.api.history.attempt_audit_store.list"
    )
    def test_list_attempt_audits(
        self,
        mock_list,
    ) -> None:
        mock_list.return_value = [
            {
                "audit_id": "audit-1",
                "task_id": "task-1",
                "event_type": "claimed",
            }
        ]

        response = list_attempt_audits(
            task_id="task-1",
            event_type="claimed",
            limit=25,
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["count"],
            1,
        )

        self.assertEqual(
            response["order"],
            "newest_first",
        )

        mock_list.assert_called_once_with(
            task_id="task-1",
            event_type="claimed",
            owner_id="local-user",
            limit=25,
        )

    @patch(
        "app.api.history.attempt_audit_store.list",
        side_effect=ValueError(
            "Unsupported audit event type: bad"
        ),
    )
    def test_invalid_audit_filter_returns_400(
        self,
        mock_list,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            list_attempt_audits(
                event_type="bad",
                limit=10,
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

    @patch(
        "app.api.history.attempt_audit_store.get"
    )
    def test_get_attempt_audit(
        self,
        mock_get,
    ) -> None:
        mock_get.return_value = {
            "audit_id": "audit-1",
            "task_id": "task-1",
            "owner_id": "local-user",
            "event_type": "completed",
        }

        response = get_attempt_audit(
            "audit-1"
        )

        self.assertEqual(
            response["attempt"]["event_type"],
            "completed",
        )

        mock_get.assert_called_once_with(
            "audit-1",
            owner_id="local-user",
        )


    @patch(
        "app.api.history.task_queue_store.get",
        return_value=None,
    )
    @patch(
        "app.api.history.attempt_audit_store.get"
    )
    def test_ownerless_orphan_audit_fails_closed(
        self,
        mock_get,
        mock_queue_get,
    ) -> None:
        mock_get.return_value = {
            "audit_id": "audit-orphan",
            "task_id": "missing-task",
            "owner_id": None,
            "event_type": "enqueued",
        }

        with self.assertRaises(HTTPException) as context:
            get_attempt_audit("audit-orphan")

        self.assertEqual(context.exception.status_code, 404)

    @patch(
        "app.api.history.attempt_audit_store.get"
    )
    def test_missing_attempt_audit_returns_404(
        self,
        mock_get,
    ) -> None:
        mock_get.return_value = None

        with self.assertRaises(
            HTTPException
        ) as context:
            get_attempt_audit(
                "missing-audit"
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    @patch(
        "app.api.tasks.attempt_audit_store.list"
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_task_history_is_chronological(
        self,
        mock_queue_get,
        mock_audit_list,
    ) -> None:
        request = self.create_pending_task()

        mock_queue_get.return_value = {
            "task_id": request.task_id,
            "owner_id": "local-user",
            "status": "claimed",
            "attempts": 1,
        }

        mock_audit_list.return_value = [
            {
                "audit_id": "audit-2",
                "task_id": request.task_id,
                "event_type": "claimed",
            },
            {
                "audit_id": "audit-1",
                "task_id": request.task_id,
                "event_type": "enqueued",
            },
        ]

        response = get_task_history(
            request.task_id,
            limit=50,
        )

        self.assertTrue(
            response["success"]
        )

        self.assertEqual(
            response["count"],
            2,
        )

        self.assertEqual(
            response["order"],
            "oldest_first",
        )

        self.assertEqual(
            [
                item["event_type"]
                for item in response["history"]
            ],
            [
                "enqueued",
                "claimed",
            ],
        )

        mock_audit_list.assert_called_once_with(
            task_id=request.task_id,
            owner_id="local-user",
            limit=50,
        )

    @patch(
        "app.api.tasks.attempt_audit_store.list"
    )
    def test_missing_task_history_returns_404(
        self,
        mock_audit_list,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            get_task_history(
                "missing-task",
                limit=20,
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

        mock_audit_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()