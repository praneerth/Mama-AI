import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.security_event_db import (
    SECURITY_EVENT_TABLE,
    SQLiteSecurityEventStore,
    sanitize_metadata,
)


class TestSQLiteSecurityEventStore(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.database_path = (
            Path(self.temp_directory.name)
            / "security-events.db"
        )
        self.store = SQLiteSecurityEventStore(
            self.database_path
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_security_event_table_is_created(
        self,
    ) -> None:
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
                (SECURITY_EVENT_TABLE,),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_append_and_get_event(
        self,
    ) -> None:
        created = self.store.append(
            event_type="invalid_token",
            severity="warning",
            client_ref="client-ref-1",
            owner_id="local-user",
            request_method="get",
            request_path="/history",
            status_code=401,
            message="Invalid bearer token.",
            metadata={
                "failure_count": 1,
            },
        )

        loaded = self.store.get(
            created["event_id"]
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(
            loaded["event_type"],
            "invalid_token",
        )
        self.assertEqual(
            loaded["request_method"],
            "GET",
        )
        self.assertEqual(
            loaded["metadata"],
            {"failure_count": 1},
        )

    def test_list_filters_by_event_type(
        self,
    ) -> None:
        self.store.append(
            event_type="invalid_token",
            severity="warning",
        )
        self.store.append(
            event_type="rate_limit_exceeded",
            severity="warning",
        )

        records = self.store.list(
            event_type="rate_limit_exceeded"
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["event_type"],
            "rate_limit_exceeded",
        )

    def test_list_filters_by_severity(
        self,
    ) -> None:
        self.store.append(
            event_type="authentication_failed",
            severity="warning",
        )
        self.store.append(
            event_type="security_configuration_error",
            severity="error",
        )

        records = self.store.list(
            severity="error"
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["severity"],
            "error",
        )

    def test_count_filters_records(
        self,
    ) -> None:
        self.store.append(
            event_type="owner_mismatch",
            severity="warning",
            owner_id="local-user",
        )
        self.store.append(
            event_type="owner_mismatch",
            severity="warning",
            owner_id="other-owner",
        )

        self.assertEqual(
            self.store.count(
                event_type="owner_mismatch",
                owner_id="local-user",
            ),
            1,
        )

    def test_external_transaction_can_roll_back(
        self,
    ) -> None:
        connection = sqlite3.connect(
            self.database_path
        )

        try:
            connection.execute("BEGIN")
            self.store.append(
                event_type="rate_limit_exceeded",
                severity="warning",
                connection=connection,
            )
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(
            self.store.count(),
            0,
        )

    def test_sensitive_metadata_is_redacted(
        self,
    ) -> None:
        metadata = sanitize_metadata(
            {
                "authorization": (
                    "Bearer secret-token"
                ),
                "nested": {
                    "api_key": "secret-key",
                    "message": (
                        "Authorization failed for "
                        "Bearer another-secret"
                    ),
                },
                "client_ip": "192.0.2.1",
            }
        )

        self.assertEqual(
            metadata["authorization"],
            "[REDACTED]",
        )
        self.assertEqual(
            metadata["nested"]["api_key"],
            "[REDACTED]",
        )
        self.assertEqual(
            metadata["client_ip"],
            "[REDACTED]",
        )
        self.assertNotIn(
            "another-secret",
            metadata["nested"]["message"],
        )

    def test_append_sanitizes_metadata(
        self,
    ) -> None:
        created = self.store.append(
            event_type="invalid_token",
            severity="warning",
            metadata={
                "token": "raw-secret",
                "note": (
                    "Bearer raw-secret-two"
                ),
            },
        )

        loaded = self.store.get(
            created["event_id"]
        )

        self.assertEqual(
            loaded["metadata"]["token"],
            "[REDACTED]",
        )
        self.assertEqual(
            loaded["metadata"]["note"],
            "Bearer [REDACTED]",
        )

    def test_invalid_event_type_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.store.append(
                event_type="unknown_event",
                severity="warning",
            )

    def test_invalid_severity_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.store.append(
                event_type="invalid_token",
                severity="debug",
            )

    def test_invalid_status_code_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.store.append(
                event_type="invalid_token",
                severity="warning",
                status_code=99,
            )

    def test_negative_retry_after_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.store.append(
                event_type="rate_limit_exceeded",
                severity="warning",
                retry_after_seconds=-1,
            )

    def test_limit_is_validated(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.store.list(limit=1001)


if __name__ == "__main__":
    unittest.main()
