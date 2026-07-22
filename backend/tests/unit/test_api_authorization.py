import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.auth import (
    require_resource_owner,
    resolve_requested_owner,
)
from app.api.tasks import (
    get_task_queue,
    list_queue,
)
from app.config import settings
from main import app


class TestAPIAuthorization(
    unittest.TestCase
):

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    def test_legacy_owner_must_match_principal(
        self,
    ) -> None:
        self.assertEqual(
            resolve_requested_owner(
                "local-user"
            ),
            "local-user",
        )

        with self.assertRaises(
            HTTPException
        ) as context:
            resolve_requested_owner(
                "other-user"
            )

        self.assertEqual(
            context.exception.status_code,
            403,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    def test_other_owner_resource_is_hidden(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            require_resource_owner(
                "other-user",
                resource_name="Task",
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch(
        "app.api.tasks.task_queue_store.list"
    )
    def test_queue_listing_uses_authenticated_owner(
        self,
        mock_list,
    ) -> None:
        mock_list.return_value = []

        response = list_queue(
            status="queued",
            owner_id=None,
            limit=20,
        )

        self.assertTrue(
            response["success"]
        )

        mock_list.assert_called_once_with(
            status="queued",
            owner_id="local-user",
            limit=20,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch(
        "app.api.tasks.task_queue_store.get"
    )
    def test_task_queue_rejects_other_owner(
        self,
        mock_get,
    ) -> None:
        mock_get.return_value = {
            "task_id": "task-1",
            "owner_id": "other-user",
            "status": "queued",
        }

        with self.assertRaises(
            HTTPException
        ) as context:
            get_task_queue(
                "task-1"
            )

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    def test_sensitive_routes_use_bearer_security(
        self,
    ) -> None:
        schema = app.openapi()

        protected_operations = {
            ("/chat", "post"),
            ("/tasks", "get"),
            ("/queue", "get"),
            ("/approvals", "get"),
            ("/history", "get"),
            ("/audit/attempts", "get"),
            ("/memory", "get"),
            ("/memory", "post"),
        }

        for path, method in protected_operations:
            operation = schema["paths"][
                path
            ][method]

            self.assertIn(
                {
                    "HTTPBearer": [],
                },
                operation.get(
                    "security",
                    [],
                ),
            )

    def test_health_remains_public(
        self,
    ) -> None:
        schema = app.openapi()

        operation = schema["paths"][
            "/health"
        ]["get"]

        self.assertFalse(
            operation.get(
                "security"
            )
        )


if __name__ == "__main__":
    unittest.main()