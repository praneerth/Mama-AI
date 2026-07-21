import unittest
from unittest.mock import Mock

from app.core.approval_registry import (
    ApprovalRegistry,
    ApprovalStatus,
)
from app.core.engine import MamaEngine
from app.core.event_bus import EventBus
from app.core.risk_policy import RiskPolicy
from app.core.task import RiskLevel, TaskRequest, TaskStatus
from app.core.task_registry import TaskRegistry


class TestEngineSecurity(unittest.TestCase):

    def create_engine(self, executor):
        self.bus = EventBus()
        self.registry = TaskRegistry()
        self.approvals = ApprovalRegistry()

        return MamaEngine(
            executor=executor,
            bus=self.bus,
            registry=self.registry,
            policy=RiskPolicy(),
            approvals=self.approvals,
        )

    def test_low_risk_command_executes_normally(self):
        executor = Mock(return_value="Notepad opened.")
        engine = self.create_engine(executor)

        result = engine.execute("open notepad")

        self.assertTrue(result.success)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        executor.assert_called_once_with("open notepad")

    def test_high_risk_command_waits_for_approval(self):
        executor = Mock(return_value="File deleted.")
        engine = self.create_engine(executor)

        result = engine.execute(
            "delete the file report.pdf",
            owner_id="user-1",
        )

        record = engine.registry.get(result.task_id)

        self.assertEqual(
            result.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertEqual(
            record.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertEqual(
            record.risk_level,
            RiskLevel.HIGH,
        )
        self.assertIn("approval", result.output)
        executor.assert_not_called()

    def test_approved_command_executes(self):
        executor = Mock(return_value="File deleted.")
        engine = self.create_engine(executor)

        request = TaskRequest(
            command="delete the file report.pdf"
        )

        waiting = engine.execute(
            request,
            owner_id="user-1",
        )

        approval_id = waiting.output[
            "approval"
        ]["approval_id"]

        grant = engine.approvals.approve(
            approval_id,
            owner_id="user-1",
        )

        result = engine.execute(
            request,
            owner_id="user-1",
            approval_id=approval_id,
            approval_token=grant.token,
        )

        record = engine.registry.get(request.task_id)
        approval = engine.approvals.get(approval_id)

        self.assertTrue(result.success)
        self.assertEqual(
            record.status,
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            approval.status,
            ApprovalStatus.CONSUMED,
        )
        executor.assert_called_once_with(
            "delete the file report.pdf"
        )

    def test_wrong_token_does_not_execute(self):
        executor = Mock(return_value="File deleted.")
        engine = self.create_engine(executor)

        request = TaskRequest(
            command="delete the file report.pdf"
        )

        waiting = engine.execute(
            request,
            owner_id="user-1",
        )

        approval_id = waiting.output[
            "approval"
        ]["approval_id"]

        engine.approvals.approve(
            approval_id,
            owner_id="user-1",
        )

        result = engine.execute(
            request,
            owner_id="user-1",
            approval_id=approval_id,
            approval_token="wrong-token",
        )

        record = engine.registry.get(request.task_id)

        self.assertEqual(
            result.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertEqual(
            record.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertIn(
            "Invalid approval token",
            result.error,
        )
        executor.assert_not_called()

    def test_denied_command_never_reaches_executor(self):
        executor = Mock(return_value="Should not execute")
        engine = self.create_engine(executor)

        result = engine.execute(
            "steal saved browser passwords"
        )

        record = engine.registry.get(result.task_id)

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(record.status, TaskStatus.FAILED)
        executor.assert_not_called()

    def test_shutdown_requires_approval(self):
        executor = Mock(return_value="Computer shutdown.")
        engine = self.create_engine(executor)

        result = engine.execute(
            "shutdown the computer",
            owner_id="user-1",
        )

        self.assertEqual(
            result.status,
            TaskStatus.WAITING_APPROVAL,
        )
        self.assertEqual(
            result.output["risk_assessment"]["risk_level"],
            "critical",
        )
        executor.assert_not_called()


if __name__ == "__main__":
    unittest.main()