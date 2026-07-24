import sys
import types
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
pipeline_stub = types.ModuleType("app.services.ai_pipeline")
pipeline_stub.process_request = lambda message: {
    "intent": "general_chat",
    "decision": "stubbed",
}
sys.modules.setdefault(
    "app.services.ai_pipeline",
    pipeline_stub,
)

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

    def test_every_non_public_operation_uses_bearer_security(
        self,
    ) -> None:
        schema = app.openapi()

        public_operations = {
            ("/", "get"),
            ("/health", "get"),
            ("/health/ready", "get"),
            ("/auth/register", "post"),
            ("/auth/login", "post"),
            ("/auth/two-factor/login/verify", "post"),
            ("/auth/refresh", "post"),
            ("/auth/email-verification/confirm", "post"),
            ("/auth/password/forgot", "post"),
            ("/auth/password/reset", "post"),
        }

        http_methods = {
            "get", "post", "put", "patch", "delete",
        }

        checked = set()

        for path, path_item in schema["paths"].items():
            for method, operation in path_item.items():
                if method not in http_methods:
                    continue

                key = (path, method)
                checked.add(key)

                if key in public_operations:
                    self.assertFalse(operation.get("security"), key)
                    continue

                self.assertIn(
                    {"HTTPBearer": []},
                    operation.get("security", []),
                    key,
                )

        self.assertTrue(public_operations.issubset(checked))

    def test_probe_endpoints_remain_public(
        self,
    ) -> None:
        schema = app.openapi()

        for path in ("/health", "/health/ready"):
            operation = schema["paths"][path]["get"]
            self.assertFalse(operation.get("security"))


if __name__ == "__main__":
    unittest.main()