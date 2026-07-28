from contextlib import closing

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.attempt_audit_db import SQLiteAttemptAuditStore


class TestMultiUserAttemptAudit(unittest.TestCase):
    def test_owner_filters_and_get_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAttemptAuditStore(Path(directory) / "audit.db")
            first = store.append(
                task_id="task-1",
                owner_id="user-1",
                attempt=0,
                event_type="enqueued",
                queue_status="queued",
            )
            store.append(
                task_id="task-2",
                owner_id="user-2",
                attempt=0,
                event_type="enqueued",
                queue_status="queued",
            )

            self.assertEqual(len(store.list(owner_id="user-1")), 1)
            self.assertEqual(store.count(owner_id="user-2"), 1)
            self.assertIsNotNone(store.get(first["audit_id"], owner_id="user-1"))
            self.assertIsNone(store.get(first["audit_id"], owner_id="user-2"))

    def test_legacy_audit_owner_migrates_from_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE task_queue (
                        task_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL
                    );
                    CREATE TABLE task_attempt_audit (
                        sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        audit_id TEXT NOT NULL UNIQUE,
                        task_id TEXT NOT NULL,
                        attempt INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        queue_status TEXT NOT NULL,
                        worker_id TEXT,
                        message TEXT,
                        error TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    INSERT INTO task_queue(task_id, owner_id)
                    VALUES ('task-1', 'user-9');
                    INSERT INTO task_attempt_audit (
                        audit_id, task_id, attempt, event_type,
                        queue_status, created_at
                    ) VALUES (
                        'audit-1', 'task-1', 0, 'enqueued',
                        'queued', '2026-01-01'
                    );
                    """
                )
                connection.commit()

            store = SQLiteAttemptAuditStore(path)
            migrated = store.get("audit-1")
            self.assertEqual(migrated["owner_id"], "user-9")


if __name__ == "__main__":
    unittest.main()
