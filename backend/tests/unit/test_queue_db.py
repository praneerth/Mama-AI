import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.queue_db import (
    QUEUE_TABLE,
    SQLiteTaskQueueStore,
)


class FakeClock:

    def __init__(self):
        self.current = datetime(
            2026,
            7,
            21,
            14,
            0,
            tzinfo=timezone.utc,
        )

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


class TestSQLiteTaskQueueStore(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp_directory.name)
            / "queue_test.db"
        )

        self.clock = FakeClock()

        self.queue = SQLiteTaskQueueStore(
            self.database_path,
            clock=self.clock,
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_queue_table_is_created(self):
        with sqlite3.connect(
            self.database_path
        ) as connection:
            row = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                AND name = ?
                """,
                (QUEUE_TABLE,),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_enqueue_and_get(self):
        queued = self.queue.enqueue(
            "task-1",
            owner_id="user-1",
        )

        loaded = self.queue.get("task-1")

        self.assertEqual(
            queued["status"],
            "queued",
        )
        self.assertEqual(
            loaded["owner_id"],
            "user-1",
        )
        self.assertEqual(
            loaded["attempts"],
            0,
        )

    def test_duplicate_task_is_rejected(self):
        self.queue.enqueue("task-1")

        with self.assertRaises(ValueError):
            self.queue.enqueue("task-1")

    def test_worker_claims_task(self):
        self.queue.enqueue("task-1")

        claimed = self.queue.claim_next(
            worker_id="worker-1",
            lease_seconds=60,
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(
            claimed["status"],
            "claimed",
        )
        self.assertEqual(
            claimed["worker_id"],
            "worker-1",
        )
        self.assertEqual(
            claimed["attempts"],
            1,
        )

    def test_expired_lease_can_be_reclaimed(self):
        self.queue.enqueue(
            "task-1",
            max_attempts=3,
        )

        first = self.queue.claim_next(
            worker_id="worker-1",
            lease_seconds=10,
        )

        self.clock.advance(11)

        second = self.queue.claim_next(
            worker_id="worker-2",
            lease_seconds=10,
        )

        self.assertEqual(
            first["task_id"],
            second["task_id"],
        )
        self.assertEqual(
            second["worker_id"],
            "worker-2",
        )
        self.assertEqual(
            second["attempts"],
            2,
        )

    def test_failed_task_retries_then_stops(self):
        self.queue.enqueue(
            "task-1",
            max_attempts=2,
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        retried = self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="First failure",
        )

        self.assertEqual(
            retried["status"],
            "queued",
        )

        self.queue.claim_next(
            worker_id="worker-1",
        )

        failed = self.queue.fail(
            "task-1",
            worker_id="worker-1",
            error="Second failure",
        )

        self.assertEqual(
            failed["status"],
            "failed",
        )
        self.assertEqual(
            failed["attempts"],
            2,
        )

    def test_complete_claimed_task(self):
        self.queue.enqueue("task-1")

        self.queue.claim_next(
            worker_id="worker-1",
        )

        completed = self.queue.complete(
            "task-1",
            worker_id="worker-1",
        )

        self.assertEqual(
            completed["status"],
            "completed",
        )
        self.assertIsNone(
            completed["worker_id"]
        )

    def test_cancel_queued_task(self):
        self.queue.enqueue("task-1")

        cancelled = self.queue.cancel(
            "task-1"
        )

        self.assertEqual(
            cancelled["status"],
            "cancelled",
        )

        claimed = self.queue.claim_next(
            worker_id="worker-1",
        )

        self.assertIsNone(claimed)


if __name__ == "__main__":
    unittest.main()