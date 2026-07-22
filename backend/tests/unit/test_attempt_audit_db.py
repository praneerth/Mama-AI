import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.attempt_audit_db import (
    ATTEMPT_AUDIT_TABLE,
    SQLiteAttemptAuditStore,
)


class TestSQLiteAttemptAuditStore(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.database_path = (
            Path(self.temp_directory.name)
            / "attempt_audit_test.db"
        )

        self.store = SQLiteAttemptAuditStore(
            self.database_path
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_audit_table_is_created(
        self,
    ) -> None:
        with sqlite3.connect(
            self.database_path
        ) as connection:
            row = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE
                    type = 'table'
                    AND name = ?
                """,
                (ATTEMPT_AUDIT_TABLE,),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_append_and_get_event(
        self,
    ) -> None:
        created = self.store.append(
            task_id="task-1",
            attempt=1,
            event_type="claimed",
            queue_status="claimed",
            worker_id="worker-1",
            message="Task claimed.",
            created_at=(
                "2026-01-01T00:00:00+00:00"
            ),
        )

        stored = self.store.get(
            created["audit_id"]
        )

        self.assertEqual(
            stored,
            created,
        )

    def test_metadata_round_trip(
        self,
    ) -> None:
        created = self.store.append(
            task_id="task-1",
            attempt=2,
            event_type="retry_scheduled",
            queue_status="queued",
            error="Temporary failure",
            metadata={
                "delay_seconds": 10,
                "reason": "transport",
            },
        )

        stored = self.store.get(
            created["audit_id"]
        )

        self.assertEqual(
            stored["metadata"],
            {
                "delay_seconds": 10,
                "reason": "transport",
            },
        )

    def test_list_filters_by_task(
        self,
    ) -> None:
        self.store.append(
            task_id="task-1",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        self.store.append(
            task_id="task-2",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        records = self.store.list(
            task_id="task-1"
        )

        self.assertEqual(
            len(records),
            1,
        )

        self.assertEqual(
            records[0]["task_id"],
            "task-1",
        )

    def test_list_filters_by_event_type(
        self,
    ) -> None:
        self.store.append(
            task_id="task-1",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        self.store.append(
            task_id="task-1",
            attempt=1,
            event_type="claimed",
            queue_status="claimed",
        )

        records = self.store.list(
            event_type="claimed"
        )

        self.assertEqual(
            len(records),
            1,
        )

        self.assertEqual(
            records[0]["event_type"],
            "claimed",
        )

    def test_count_filters_records(
        self,
    ) -> None:
        self.store.append(
            task_id="task-1",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        self.store.append(
            task_id="task-1",
            attempt=1,
            event_type="claimed",
            queue_status="claimed",
        )

        self.store.append(
            task_id="task-2",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        self.assertEqual(
            self.store.count(),
            3,
        )

        self.assertEqual(
            self.store.count(
                task_id="task-1"
            ),
            2,
        )

        self.assertEqual(
            self.store.count(
                event_type="enqueued"
            ),
            2,
        )

    def test_external_transaction_can_roll_back_audit(
        self,
    ) -> None:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
        )

        connection.row_factory = sqlite3.Row

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            self.store.append(
                task_id="task-1",
                attempt=1,
                event_type="claimed",
                queue_status="claimed",
                worker_id="worker-1",
                connection=connection,
            )

            connection.rollback()

        finally:
            connection.close()

        self.assertEqual(
            self.store.count(),
            0,
        )

    def test_invalid_event_type_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.store.append(
                task_id="task-1",
                attempt=0,
                event_type="unknown",
                queue_status="queued",
            )

    def test_invalid_queue_status_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.store.append(
                task_id="task-1",
                attempt=0,
                event_type="enqueued",
                queue_status="unknown",
            )

    def test_negative_attempt_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.store.append(
                task_id="task-1",
                attempt=-1,
                event_type="enqueued",
                queue_status="queued",
            )


if __name__ == "__main__":
    unittest.main()