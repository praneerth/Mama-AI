import tempfile
import unittest
from pathlib import Path

from app.database.attempt_audit_db import (
    SQLiteAttemptAuditStore,
)
from app.database.queue_db import (
    SQLiteTaskQueueStore,
)


class FailingAuditStore:
    def initialize(self) -> None:
        pass

    def append(self, **kwargs):
        raise RuntimeError(
            "Audit storage unavailable"
        )


class TestQueueAuditIntegration(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temp_directory.name)
            / "queue_audit_test.db"
        )

        self.audit = SQLiteAttemptAuditStore(
            self.database_path
        )

        self.queue = SQLiteTaskQueueStore(
            self.database_path,
            audit_store=self.audit,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def events(
        self,
        task_id: str,
    ) -> list[dict]:
        return list(
            reversed(
                self.audit.list(
                    task_id=task_id,
                    limit=100,
                )
            )
        )

    def event_names(
        self,
        task_id: str,
    ) -> list[str]:
        return [
            record["event_type"]
            for record in self.events(
                task_id
            )
        ]

    def test_enqueue_and_claim_are_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1"
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        events = self.events(
            "task-1"
        )

        self.assertEqual(
            [
                event["event_type"]
                for event in events
            ],
            [
                "enqueued",
                "claimed",
            ],
        )

        self.assertEqual(
            events[1]["attempt"],
            1,
        )

        self.assertEqual(
            events[1]["worker_id"],
            "worker-1",
        )

    def test_automatic_retry_and_failure_are_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=2,
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Temporary failure",
            retry_delay_seconds=0,
        )

        self.queue.claim_next(
            worker_id="worker-2"
        )

        self.queue.fail(
            "task-1",
            worker_id="worker-2",
            error="Permanent failure",
        )

        self.assertEqual(
            self.event_names("task-1"),
            [
                "enqueued",
                "claimed",
                "retry_scheduled",
                "claimed",
                "failed",
            ],
        )

        final_event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            final_event["queue_status"],
            "failed",
        )

        self.assertEqual(
            final_event["error"],
            "Permanent failure",
        )

    def test_manual_retry_is_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Delivery failed",
        )

        self.queue.retry_failed(
            "task-1",
            max_attempts=4,
            delay_seconds=10,
        )

        event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            event["event_type"],
            "manually_retried",
        )

        self.assertEqual(
            event["attempt"],
            0,
        )

        self.assertEqual(
            event["metadata"][
                "previous_attempts"
            ],
            1,
        )

        self.assertEqual(
            event["metadata"][
                "new_max_attempts"
            ],
            4,
        )

    def test_completion_is_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1"
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        self.queue.complete(
            "task-1",
            worker_id="worker-1",
        )

        event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            event["event_type"],
            "completed",
        )

        self.assertEqual(
            event["queue_status"],
            "completed",
        )

        self.assertEqual(
            event["worker_id"],
            "worker-1",
        )

    def test_safe_cancellation_is_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1"
        )

        self.queue.cancel_queued(
            "task-1"
        )

        event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            event["event_type"],
            "cancelled",
        )

        self.assertEqual(
            event["metadata"][
                "cancellation_mode"
            ],
            "safe_queued",
        )

    def test_internal_claimed_cancellation_is_audited(
        self,
    ) -> None:
        self.queue.enqueue(
            "task-1"
        )

        self.queue.claim_next(
            worker_id="worker-1"
        )

        self.queue.cancel(
            "task-1"
        )

        event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            event["event_type"],
            "cancelled",
        )

        self.assertEqual(
            event["worker_id"],
            "worker-1",
        )

        self.assertEqual(
            event["metadata"][
                "cancellation_mode"
            ],
            "internal",
        )

    def test_expired_exhausted_claim_is_audited(
        self,
    ) -> None:
        from datetime import (
            datetime,
            timedelta,
            timezone,
        )

        class Clock:
            def __init__(self):
                self.current = datetime(
                    2026,
                    1,
                    1,
                    tzinfo=timezone.utc,
                )

            def __call__(self):
                return self.current

        clock = Clock()

        queue = SQLiteTaskQueueStore(
            self.database_path,
            clock=clock,
            audit_store=self.audit,
        )

        queue.enqueue(
            "task-1",
            max_attempts=1,
        )

        queue.claim_next(
            worker_id="worker-1",
            lease_seconds=5,
        )

        clock.current += timedelta(
            seconds=6
        )

        self.assertIsNone(
            queue.claim_next(
                worker_id="worker-2",
                lease_seconds=5,
            )
        )

        stored = queue.get(
            "task-1"
        )

        self.assertEqual(
            stored["status"],
            "failed",
        )

        event = self.events(
            "task-1"
        )[-1]

        self.assertEqual(
            event["event_type"],
            "failed",
        )

        self.assertEqual(
            event["metadata"]["reason"],
            "lease_expired",
        )

    def test_enqueue_rolls_back_when_audit_fails(
        self,
    ) -> None:
        database_path = (
            Path(self.temp_directory.name)
            / "rollback_test.db"
        )

        queue = SQLiteTaskQueueStore(
            database_path,
            audit_store=FailingAuditStore(),
        )

        with self.assertRaises(
            RuntimeError
        ):
            queue.enqueue(
                "task-1"
            )

        self.assertIsNone(
            queue.get("task-1")
        )

    def test_claim_rolls_back_when_audit_fails(
        self,
    ) -> None:
        database_path = (
            Path(self.temp_directory.name)
            / "claim_rollback_test.db"
        )

        normal_audit = (
            SQLiteAttemptAuditStore(
                database_path
            )
        )

        queue = SQLiteTaskQueueStore(
            database_path,
            audit_store=normal_audit,
        )

        queue.enqueue(
            "task-1"
        )

        queue._audit = (
            FailingAuditStore()
        )

        with self.assertRaises(
            RuntimeError
        ):
            queue.claim_next(
                worker_id="worker-1"
            )

        stored = queue.get(
            "task-1"
        )

        self.assertEqual(
            stored["status"],
            "queued",
        )

        self.assertEqual(
            stored["attempts"],
            0,
        )


if __name__ == "__main__":
    unittest.main()