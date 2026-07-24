import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.security_event_db import (
    SECURITY_EVENT_TABLE,
    SQLiteSecurityEventStore,
)


class TestRBACSecurityEventMigration(unittest.TestCase):
    def test_legacy_event_constraint_is_migrated_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "security.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    f"""
                    CREATE TABLE {SECURITY_EVENT_TABLE} (
                        sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        event_type TEXT NOT NULL CHECK (
                            event_type IN ('invalid_token', 'owner_mismatch')
                        ),
                        severity TEXT NOT NULL CHECK (
                            severity IN ('info', 'warning', 'error', 'critical')
                        ),
                        client_ref TEXT,
                        owner_id TEXT,
                        request_method TEXT,
                        request_path TEXT,
                        status_code INTEGER,
                        retry_after_seconds INTEGER,
                        message TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{{}}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    f"""
                    INSERT INTO {SECURITY_EVENT_TABLE} (
                        event_id, event_type, severity,
                        metadata_json, created_at
                    ) VALUES ('old-event', 'invalid_token', 'warning', '{{}}', '2026-07-23T12:00:00+00:00')
                    """
                )
            store = SQLiteSecurityEventStore(path)
            created = store.append(
                event_type="authorization_denied",
                severity="warning",
            )
            self.assertIsNotNone(store.get("old-event"))
            self.assertEqual(
                store.get(created["event_id"])["event_type"],
                "authorization_denied",
            )


if __name__ == "__main__":
    unittest.main()
