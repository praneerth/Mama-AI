import unittest
from datetime import datetime, timedelta, timezone

from app.core.approval_registry import (
    ApprovalRegistry,
    ApprovalStatus,
)
from app.core.task import RiskLevel


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


class TestApprovalRegistry(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.registry = ApprovalRegistry(clock=self.clock)

    def create_request(self, ttl_seconds=300):
        return self.registry.create(
            task_id="task-123",
            owner_id="user-123",
            command="delete the file report.pdf",
            risk_level=RiskLevel.HIGH,
            reasons=["File deletion requires approval."],
            ttl_seconds=ttl_seconds,
        )

    def test_create_pending_request(self):
        record = self.create_request()

        self.assertEqual(
            record.status,
            ApprovalStatus.PENDING,
        )
        self.assertEqual(record.task_id, "task-123")
        self.assertEqual(record.owner_id, "user-123")
        self.assertNotIn("token_hash", record.to_dict())

    def test_approve_and_consume_token(self):
        record = self.create_request()

        grant = self.registry.approve(
            record.approval_id,
            owner_id="user-123",
        )

        consumed = self.registry.consume(
            record.approval_id,
            task_id="task-123",
            owner_id="user-123",
            token=grant.token,
        )

        self.assertEqual(
            consumed.status,
            ApprovalStatus.CONSUMED,
        )
        self.assertIsNotNone(consumed.consumed_at)

    def test_token_can_only_be_used_once(self):
        record = self.create_request()

        grant = self.registry.approve(
            record.approval_id,
            owner_id="user-123",
        )

        self.registry.consume(
            record.approval_id,
            task_id="task-123",
            owner_id="user-123",
            token=grant.token,
        )

        with self.assertRaises(PermissionError):
            self.registry.consume(
                record.approval_id,
                task_id="task-123",
                owner_id="user-123",
                token=grant.token,
            )

    def test_wrong_owner_cannot_approve(self):
        record = self.create_request()

        with self.assertRaises(PermissionError):
            self.registry.approve(
                record.approval_id,
                owner_id="another-user",
            )

    def test_wrong_token_is_rejected(self):
        record = self.create_request()

        self.registry.approve(
            record.approval_id,
            owner_id="user-123",
        )

        with self.assertRaises(PermissionError):
            self.registry.consume(
                record.approval_id,
                task_id="task-123",
                owner_id="user-123",
                token="wrong-token",
            )

    def test_token_is_bound_to_task(self):
        record = self.create_request()

        grant = self.registry.approve(
            record.approval_id,
            owner_id="user-123",
        )

        with self.assertRaises(PermissionError):
            self.registry.consume(
                record.approval_id,
                task_id="another-task",
                owner_id="user-123",
                token=grant.token,
            )

    def test_rejected_request_cannot_be_approved(self):
        record = self.create_request()

        rejected = self.registry.reject(
            record.approval_id,
            owner_id="user-123",
        )

        self.assertEqual(
            rejected.status,
            ApprovalStatus.REJECTED,
        )

        with self.assertRaises(ValueError):
            self.registry.approve(
                record.approval_id,
                owner_id="user-123",
            )

    def test_expired_request_cannot_be_approved(self):
        record = self.create_request(ttl_seconds=10)

        self.clock.advance(11)

        stored = self.registry.get(record.approval_id)

        self.assertEqual(
            stored.status,
            ApprovalStatus.EXPIRED,
        )

        with self.assertRaises(TimeoutError):
            self.registry.approve(
                record.approval_id,
                owner_id="user-123",
            )

    def test_list_can_filter_by_status_and_owner(self):
        record = self.create_request()

        self.registry.approve(
            record.approval_id,
            owner_id="user-123",
        )

        results = self.registry.list(
            status=ApprovalStatus.APPROVED,
            owner_id="user-123",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].approval_id,
            record.approval_id,
        )


if __name__ == "__main__":
    unittest.main()