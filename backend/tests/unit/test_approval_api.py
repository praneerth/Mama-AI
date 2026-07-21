import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.api.approvals import (
    ApprovalActionRequest,
    approve_and_execute,
    get_approval,
    list_approvals,
    reject_approval,
)
from app.core.engine import engine
from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskStatus,
)


class TestApprovalAPI(unittest.TestCase):

    def setUp(self):
        engine.registry.clear()
        engine.approvals.clear()

        self.owner_id = "local-user"

    def tearDown(self):
        engine.registry.clear()
        engine.approvals.clear()

    def create_pending_approval(self):
        request = TaskRequest(
            command="delete the file report.pdf",
            source="api",
            autonomy_level=2,
            risk_level=RiskLevel.HIGH,
            metadata={
                "owner_id": self.owner_id,
            },
        )

        engine.registry.register(request)

        engine.registry.mark_waiting_approval(
            request.task_id,
            message="Waiting for user approval.",
        )

        approval = engine.approvals.create(
            task_id=request.task_id,
            owner_id=self.owner_id,
            command=request.command,
            risk_level=RiskLevel.HIGH,
            reasons=[
                "Deleting files requires approval."
            ],
        )

        return request, approval

    def test_list_pending_approvals(self):
        request, approval = (
            self.create_pending_approval()
        )

        response = list_approvals(
            status="pending",
            owner_id=self.owner_id,
            limit=20,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["count"], 1)
        self.assertEqual(
            response["approvals"][0]["approval_id"],
            approval.approval_id,
        )
        self.assertEqual(
            response["approvals"][0]["task_id"],
            request.task_id,
        )

    def test_get_approval(self):
        _, approval = self.create_pending_approval()

        response = get_approval(
            approval.approval_id
        )

        self.assertTrue(response["success"])
        self.assertEqual(
            response["approval"]["status"],
            "pending",
        )
        self.assertNotIn(
            "token",
            response["approval"],
        )

    def test_approve_executes_and_consumes_token(self):
        request, approval = (
            self.create_pending_approval()
        )

        executor = Mock(
            return_value="Mock file deletion completed."
        )

        with patch.object(
            engine,
            "_executor",
            executor,
        ):
            response = approve_and_execute(
                approval.approval_id,
                ApprovalActionRequest(
                    owner_id=self.owner_id
                ),
            )

        stored_task = engine.registry.get(
            request.task_id
        )
        stored_approval = engine.approvals.get(
            approval.approval_id
        )

        self.assertTrue(response["success"])
        self.assertEqual(
            stored_task.status,
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            stored_approval.status.value,
            "consumed",
        )
        self.assertNotIn(
            "token",
            response["approval"],
        )

        executor.assert_called_once_with(
            "delete the file report.pdf"
        )

    def test_reject_cancels_task(self):
        request, approval = (
            self.create_pending_approval()
        )

        response = reject_approval(
            approval.approval_id,
            ApprovalActionRequest(
                owner_id=self.owner_id
            ),
        )

        stored_task = engine.registry.get(
            request.task_id
        )

        self.assertTrue(response["success"])
        self.assertEqual(
            response["approval"]["status"],
            "rejected",
        )
        self.assertEqual(
            stored_task.status,
            TaskStatus.CANCELLED,
        )

    def test_wrong_owner_is_forbidden(self):
        _, approval = self.create_pending_approval()

        with self.assertRaises(HTTPException) as context:
            approve_and_execute(
                approval.approval_id,
                ApprovalActionRequest(
                    owner_id="another-user"
                ),
            )

        self.assertEqual(
            context.exception.status_code,
            403,
        )

    def test_missing_approval_returns_404(self):
        with self.assertRaises(HTTPException) as context:
            get_approval("missing-approval")

        self.assertEqual(
            context.exception.status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()