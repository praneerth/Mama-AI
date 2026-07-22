import sqlite3
import tempfile
import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

from app.database.idempotency_db import (
    IDEMPOTENCY_TABLE,
    IdempotencyConflictError,
    SQLiteIdempotencyStore,
    fingerprint_idempotency_key,
    fingerprint_request_payload,
)


class MutableClock:

    def __init__(
        self,
        current: datetime,
    ) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(
        self,
        *,
        seconds: int,
    ) -> None:
        self.current = (
            self.current
            + timedelta(
                seconds=seconds
            )
        )


class TestSQLiteIdempotencyStore(
    unittest.TestCase
):

    KEY = (
        "mama-ai-idempotency-key-0001"
    )

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.database_path = (
            Path(
                self.temp_directory.name
            )
            / "idempotency.db"
        )
        self.clock = MutableClock(
            datetime(
                2026,
                7,
                22,
                10,
                0,
                tzinfo=timezone.utc,
            )
        )
        self.store = (
            SQLiteIdempotencyStore(
                self.database_path,
                clock=self.clock,
            )
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def reserve(
        self,
        *,
        key: str | None = None,
        owner_id: str = "local-user",
        payload: dict | None = None,
        expiry_seconds: int = 3600,
    ) -> dict:
        return self.store.reserve(
            idempotency_key=(
                self.KEY
                if key is None
                else key
            ),
            owner_id=owner_id,
            request_method="POST",
            request_path="/chat",
            request_payload=(
                {"message": "open chrome"}
                if payload is None
                else payload
            ),
            expiry_seconds=(
                expiry_seconds
            ),
        )

    def test_table_is_created(
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
                (
                    IDEMPOTENCY_TABLE,
                ),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_new_reservation_is_processing(
        self,
    ) -> None:
        record = self.reserve()

        self.assertTrue(
            record["created"]
        )
        self.assertEqual(
            record["status"],
            "processing",
        )
        self.assertIsNone(
            record["response_body"]
        )

    def test_duplicate_request_returns_existing_record(
        self,
    ) -> None:
        first = self.reserve()
        second = self.reserve()

        self.assertFalse(
            second["created"]
        )
        self.assertEqual(
            first["record_id"],
            second["record_id"],
        )
        self.assertEqual(
            self.store.count(),
            1,
        )

    def test_same_key_different_request_conflicts(
        self,
    ) -> None:
        self.reserve()

        with self.assertRaises(
            IdempotencyConflictError
        ):
            self.reserve(
                payload={
                    "message": (
                        "delete report.pdf"
                    ),
                }
            )

    def test_same_key_is_scoped_by_owner(
        self,
    ) -> None:
        first = self.reserve(
            owner_id="local-user"
        )
        second = self.reserve(
            owner_id="other-user"
        )

        self.assertNotEqual(
            first["record_id"],
            second["record_id"],
        )
        self.assertEqual(
            self.store.count(),
            2,
        )

    def test_complete_stores_replay_response(
        self,
    ) -> None:
        self.reserve()

        completed = (
            self.store.complete(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                request_method="POST",
                request_path="/chat",
                response_status_code=200,
                response_body={
                    "success": True,
                    "task_id": "task-1",
                },
            )
        )

        self.assertEqual(
            completed["status"],
            "completed",
        )
        self.assertEqual(
            completed[
                "response_status_code"
            ],
            200,
        )
        self.assertEqual(
            completed["response_body"][
                "task_id"
            ],
            "task-1",
        )

    def test_repeated_complete_is_idempotent(
        self,
    ) -> None:
        self.reserve()

        first = self.store.complete(
            idempotency_key=self.KEY,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=200,
            response_body={
                "success": True,
                "task_id": "task-1",
            },
        )

        second = self.store.complete(
            idempotency_key=self.KEY,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=201,
            response_body={
                "success": True,
                "task_id": "task-2",
            },
        )

        self.assertEqual(
            second["record_id"],
            first["record_id"],
        )
        self.assertEqual(
            second[
                "response_status_code"
            ],
            200,
        )
        self.assertEqual(
            second["response_body"][
                "task_id"
            ],
            "task-1",
        )

    def test_fail_stores_stable_failure(
        self,
    ) -> None:
        self.reserve()

        failed = self.store.fail(
            idempotency_key=self.KEY,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=503,
            response_body={
                "success": False,
                "detail": (
                    "Queue unavailable."
                ),
            },
            error_code=(
                "queue_unavailable"
            ),
        )

        self.assertEqual(
            failed["status"],
            "failed",
        )
        self.assertEqual(
            failed["error_code"],
            "queue_unavailable",
        )
        self.assertEqual(
            failed[
                "response_status_code"
            ],
            503,
        )

    def test_raw_key_is_not_stored(
        self,
    ) -> None:
        record = self.reserve()

        with sqlite3.connect(
            self.database_path
        ) as connection:
            row = connection.execute(
                f"""
                SELECT key_fingerprint
                FROM {IDEMPOTENCY_TABLE}
                WHERE record_id = ?
                """,
                (
                    record["record_id"],
                ),
            ).fetchone()

        self.assertNotEqual(
            row[0],
            self.KEY,
        )
        self.assertEqual(
            row[0],
            fingerprint_idempotency_key(
                self.KEY
            ),
        )

    def test_request_body_is_not_stored(
        self,
    ) -> None:
        secret_message = (
            "open private-document-123"
        )

        self.reserve(
            payload={
                "message": secret_message,
            }
        )

        raw_database = (
            self.database_path.read_bytes()
        )

        self.assertNotIn(
            secret_message.encode(
                "utf-8"
            ),
            raw_database,
        )

    def test_expired_record_can_be_reserved_again(
        self,
    ) -> None:
        first = self.reserve(
            expiry_seconds=60
        )

        self.clock.advance(
            seconds=61
        )

        second = self.reserve(
            expiry_seconds=60
        )

        self.assertTrue(
            second["created"]
        )
        self.assertNotEqual(
            first["record_id"],
            second["record_id"],
        )

    def test_get_removes_expired_records(
        self,
    ) -> None:
        self.reserve(
            expiry_seconds=60
        )

        self.clock.advance(
            seconds=61
        )

        record = self.store.get(
            idempotency_key=self.KEY,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
        )

        self.assertIsNone(record)
        self.assertEqual(
            self.store.count(),
            0,
        )

    def test_delete_expired_is_bounded(
        self,
    ) -> None:
        self.reserve(
            key=(
                "mama-ai-idempotency-key-0001"
            ),
            expiry_seconds=60,
        )
        self.reserve(
            key=(
                "mama-ai-idempotency-key-0002"
            ),
            expiry_seconds=60,
        )

        self.clock.advance(
            seconds=61
        )

        deleted = (
            self.store.delete_expired(
                limit=1
            )
        )

        self.assertEqual(
            deleted,
            1,
        )

        deleted_again = (
            self.store.delete_expired(
                limit=10
            )
        )

        self.assertEqual(
            deleted_again,
            1,
        )

    def test_list_and_count_filter_status(
        self,
    ) -> None:
        self.reserve()

        second_key = (
            "mama-ai-idempotency-key-0002"
        )

        self.reserve(
            key=second_key
        )

        self.store.complete(
            idempotency_key=second_key,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=200,
            response_body={
                "success": True,
            },
        )

        records = self.store.list(
            status="completed"
        )

        self.assertEqual(
            len(records),
            1,
        )
        self.assertEqual(
            self.store.count(
                status="processing"
            ),
            1,
        )

    def test_short_key_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.reserve(
                key="too-short"
            )

    def test_invalid_response_status_is_rejected(
        self,
    ) -> None:
        self.reserve()

        with self.assertRaises(
            ValueError
        ):
            self.store.complete(
                idempotency_key=(
                    self.KEY
                ),
                owner_id="local-user",
                request_method="POST",
                request_path="/chat",
                response_status_code=99,
                response_body={
                    "success": False,
                },
            )

    def test_request_fingerprint_is_deterministic(
        self,
    ) -> None:
        first = (
            fingerprint_request_payload(
                {
                    "a": 1,
                    "b": 2,
                }
            )
        )
        second = (
            fingerprint_request_payload(
                {
                    "b": 2,
                    "a": 1,
                }
            )
        )

        self.assertEqual(
            first,
            second,
        )


if __name__ == "__main__":
    unittest.main()
