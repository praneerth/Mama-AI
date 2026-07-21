import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.approval_registry import (
    ApprovalRegistry,
    ApprovalStatus,
)
from app.core.task import RiskLevel, TaskRequest
from app.core.task_registry import TaskRegistry
from app.database.state_db import SQLiteStateStore


class FakeClock:

    def __init__(self):
        self.current = datetime(
            2026,
            7,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


class TestApprovalRegistryPersistence(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp_directory.name)
            / "approval_registry_test.db"
        )

        self.store = SQLiteStateStore(
            self.database_path
        )

        self.clock = FakeClock()

    def tearDown(self):
        self.temp_directory.cleanup()

    def create_persisted_task(self):
        request = TaskRequest(
            command="delete the file report.pdf",
            risk_level=RiskLevel.HIGH,
        )

        tasks = TaskRegistry()

        tasks.enable_persistence(
            self.store,
            restore=False,
        )

        tasks.register(request)

        return request

    def test_persistence_is_disabled_by_default(self):
        request = self.create_persisted_task()

        approvals = ApprovalRegistry(
            clock=self.clock
        )

        approval = approvals.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
        )

        self.assertFalse(
            approvals.persistence_enabled
        )

        self.assertIsNone(
            self.store.get_approval(
                approval.approval_id
            )
        )

    def test_created_approval_is_persisted(self):
        request = self.create_persisted_task()

        approvals = ApprovalRegistry(
            clock=self.clock
        )

        approvals.enable_persistence(
            self.store,
            restore=False,
        )

        approval = approvals.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
            reasons=[
                "File deletion requires approval."
            ],
        )

        stored = self.store.get_approval(
            approval.approval_id
        )

        self.assertIsNotNone(stored)
        self.assertEqual(
            stored["status"],
            ApprovalStatus.PENDING.value,
        )
        self.assertEqual(
            stored["owner_id"],
            "user-1",
        )

    def test_approved_token_survives_registry_restart(self):
        request = self.create_persisted_task()

        first_registry = ApprovalRegistry(
            clock=self.clock
        )

        first_registry.enable_persistence(
            self.store,
            restore=False,
        )

        approval = first_registry.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
        )

        grant = first_registry.approve(
            approval.approval_id,
            owner_id="user-1",
        )

        second_registry = ApprovalRegistry(
            clock=self.clock
        )

        restored_count = second_registry.enable_persistence(
            self.store,
            restore=True,
        )

        restored = second_registry.get(
            approval.approval_id
        )

        self.assertEqual(restored_count, 1)
        self.assertIsNotNone(restored)
        self.assertEqual(
            restored.status,
            ApprovalStatus.APPROVED,
        )

        consumed = second_registry.consume(
            approval.approval_id,
            task_id=request.task_id,
            owner_id="user-1",
            token=grant.token,
        )

        self.assertEqual(
            consumed.status,
            ApprovalStatus.CONSUMED,
        )

        stored = self.store.get_approval(
            approval.approval_id
        )

        self.assertEqual(
            stored["status"],
            ApprovalStatus.CONSUMED.value,
        )
        self.assertIsNone(
            stored["token_hash"]
        )

    def test_clear_only_removes_memory(self):
        request = self.create_persisted_task()

        approvals = ApprovalRegistry(
            clock=self.clock
        )

        approvals.enable_persistence(
            self.store,
            restore=False,
        )

        approval = approvals.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
        )

        approvals.clear()

        self.assertEqual(
            approvals.list(),
            [],
        )

        self.assertIsNotNone(
            self.store.get_approval(
                approval.approval_id
            )
        )

    def test_expired_approval_is_recovered(self):
        request = self.create_persisted_task()

        first_registry = ApprovalRegistry(
            clock=self.clock
        )

        first_registry.enable_persistence(
            self.store,
            restore=False,
        )

        approval = first_registry.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
            ttl_seconds=10,
        )

        self.clock.advance(11)

        second_registry = ApprovalRegistry(
            clock=self.clock
        )

        second_registry.enable_persistence(
            self.store,
            restore=True,
        )

        restored = second_registry.get(
            approval.approval_id
        )

        stored = self.store.get_approval(
            approval.approval_id
        )

        self.assertEqual(
            restored.status,
            ApprovalStatus.EXPIRED,
        )
        self.assertEqual(
            stored["status"],
            ApprovalStatus.EXPIRED.value,
        )
        self.assertIsNone(
            stored["token_hash"]
        )


if __name__ == "__main__":
    unittest.main()