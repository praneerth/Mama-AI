import tempfile
import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

from app.database.idempotency_db import (
    SQLiteIdempotencyStore,
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


class TestIdempotencyHealthSummary(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.database_path = (
            Path(
                self.temp_directory.name
            )
            / "idempotency-health.db"
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
        key: str,
        *,
        expiry_seconds: int = 3600,
    ) -> None:
        self.store.reserve(
            idempotency_key=key,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            request_payload={
                "message": key,
            },
            expiry_seconds=(
                expiry_seconds
            ),
        )

    def test_summary_counts_active_statuses(
        self,
    ) -> None:
        processing_key = (
            "health-processing-key-0001"
        )
        completed_key = (
            "health-completed-key-0001"
        )
        failed_key = (
            "health-failed-key-0001"
        )

        self.reserve(processing_key)
        self.reserve(completed_key)
        self.reserve(failed_key)

        self.store.complete(
            idempotency_key=completed_key,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=200,
            response_body={
                "success": True,
            },
        )

        self.store.fail(
            idempotency_key=failed_key,
            owner_id="local-user",
            request_method="POST",
            request_path="/chat",
            response_status_code=503,
            response_body={
                "detail": "Unavailable",
            },
            error_code="unavailable",
        )

        summary = (
            self.store.health_summary(
                stuck_after_seconds=300
            )
        )

        self.assertEqual(
            summary["total"],
            3,
        )
        self.assertEqual(
            summary["counts"],
            {
                "processing": 1,
                "completed": 1,
                "failed": 1,
            },
        )

    def test_old_processing_record_is_stuck(
        self,
    ) -> None:
        self.reserve(
            "health-stuck-key-0001"
        )

        self.clock.advance(
            seconds=301
        )

        summary = (
            self.store.health_summary(
                stuck_after_seconds=300
            )
        )

        self.assertEqual(
            summary["stuck_processing"],
            1,
        )
        self.assertIsNotNone(
            summary[
                "oldest_processing_at"
            ]
        )

    def test_expired_records_are_counted_separately(
        self,
    ) -> None:
        self.reserve(
            "health-expired-key-0001",
            expiry_seconds=60,
        )

        self.clock.advance(
            seconds=61
        )

        summary = (
            self.store.health_summary(
                stuck_after_seconds=300
            )
        )

        self.assertEqual(
            summary["total"],
            0,
        )
        self.assertEqual(
            summary["expired"],
            1,
        )

    def test_invalid_stuck_threshold_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.store.health_summary(
                stuck_after_seconds=0
            )


if __name__ == "__main__":
    unittest.main()
