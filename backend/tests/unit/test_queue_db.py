import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.queue_db import (
    QUEUE_TABLE,
    SQLiteTaskQueueStore,
)


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        )

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestSQLiteTaskQueueStore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temp_directory.name)
            / "task_queue_test.db"
        )
        self.clock = MutableClock()
        self.queue = SQLiteTaskQueueStore(
            self.database_path,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_queue_table_is_created(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (QUEUE_TABLE,),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_enqueue_and_get(self) -> None:
        created = self.queue.enqueue(
            "task-1",
            owner_id="user-1",
        )
        stored = self.queue.get("task-1")

        self.assertEqual(created["task_id"], "task-1")
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["owner_id"], "user-1")
        self.assertEqual(created["attempts"], 0)
        self.assertEqual(stored, created)

    def test_duplicate_task_is_rejected(self) -> None:
        self.queue.enqueue("task-1")

        with self.assertRaises(ValueError):
            self.queue.enqueue("task-1")

    def test_worker_claims_task(self) -> None:
        self.queue.enqueue("task-1")

        claimed = self.queue.claim_next(
            worker_id="worker-1",
            lease_seconds=30,
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["task_id"], "task-1")
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(claimed["worker_id"], "worker-1")
        self.assertEqual(claimed["attempts"], 1)
        self.assertIsNotNone(claimed["lease_expires_at"])

    def test_expired_lease_can_be_reclaimed(self) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=3,
        )

        first = self.queue.claim_next(
            worker_id="worker-1",
            lease_seconds=5,
        )

        self.assertEqual(first["attempts"], 1)

        self.clock.advance(seconds=6)

        second = self.queue.claim_next(
            worker_id="worker-2",
            lease_seconds=5,
        )

        self.assertIsNotNone(second)
        self.assertEqual(second["status"], "claimed")
        self.assertEqual(second["worker_id"], "worker-2")
        self.assertEqual(second["attempts"], 2)

    def test_failed_task_retries_then_stops(self) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=2,
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        retry = self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Temporary failure",
        )

        self.assertEqual(retry["status"], "queued")
        self.assertEqual(retry["attempts"], 1)
        self.assertEqual(
            retry["last_error"],
            "Temporary failure",
        )

        self.queue.claim_next(
            worker_id="worker-2",
        )

        failed = self.queue.fail(
            "task-1",
            worker_id="worker-2",
            error="Permanent failure",
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 2)
        self.assertEqual(
            failed["last_error"],
            "Permanent failure",
        )

    def test_complete_claimed_task(self) -> None:
        self.queue.enqueue("task-1")
        self.queue.claim_next(
            worker_id="worker-1",
        )

        completed = self.queue.complete(
            "task-1",
            worker_id="worker-1",
        )

        self.assertEqual(completed["status"], "completed")
        self.assertIsNone(completed["worker_id"])
        self.assertIsNone(completed["lease_expires_at"])
        self.assertIsNone(completed["last_error"])

    def test_cancel_queued_task(self) -> None:
        self.queue.enqueue("task-1")

        claimed = self.queue.claim_next(
            worker_id="worker-1",
        )

        self.assertEqual(claimed["status"], "claimed")

        cancelled = self.queue.cancel("task-1")

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled["worker_id"])
        self.assertIsNone(cancelled["lease_expires_at"])

    def test_cancel_queued_rejects_claimed_task(self) -> None:
        self.queue.enqueue("task-1")

        self.queue.claim_next(
            worker_id="worker-1",
        )

        with self.assertRaises(ValueError):
            self.queue.cancel_queued("task-1")

        stored = self.queue.get("task-1")

        self.assertEqual(stored["status"], "claimed")
        self.assertEqual(stored["worker_id"], "worker-1")

    def test_failed_task_can_be_manually_retried(self) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        failed = self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Worker unavailable",
        )

        self.assertEqual(
            failed["status"],
            "failed",
        )

        retried = self.queue.retry_failed(
            "task-1",
            max_attempts=2,
            delay_seconds=30,
        )

        expected_available_at = (
            self.clock.current
            + timedelta(seconds=30)
        ).isoformat()

        self.assertEqual(
            retried["status"],
            "queued",
        )
        self.assertEqual(
            retried["attempts"],
            0,
        )
        self.assertEqual(
            retried["max_attempts"],
            2,
        )
        self.assertEqual(
            retried["available_at"],
            expected_available_at,
        )
        self.assertIsNone(
            retried["worker_id"]
        )
        self.assertIsNone(
            retried["lease_expires_at"]
        )
        self.assertEqual(
            retried["last_error"],
            "Worker unavailable",
        )

    def test_retried_task_respects_delay(self) -> None:
        self.queue.enqueue(
            "task-1",
            max_attempts=1,
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Temporary failure",
        )

        self.queue.retry_failed(
            "task-1",
            max_attempts=3,
            delay_seconds=10,
        )

        unavailable = self.queue.claim_next(
            worker_id="worker-2",
        )

        self.assertIsNone(unavailable)

        self.clock.advance(seconds=10)

        claimed = self.queue.claim_next(
            worker_id="worker-2",
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(
            claimed["status"],
            "claimed",
        )
        self.assertEqual(
            claimed["attempts"],
            1,
        )

    def test_retry_failed_rejects_non_failed_task(self) -> None:
        self.queue.enqueue("task-1")

        with self.assertRaises(ValueError):
            self.queue.retry_failed(
                "task-1"
            )

        stored = self.queue.get("task-1")

        self.assertEqual(
            stored["status"],
            "queued",
        )

    def test_retry_failed_rejects_missing_task(self) -> None:
        with self.assertRaises(KeyError):
            self.queue.retry_failed(
                "missing-task"
            )


if __name__ == "__main__":
    unittest.main()