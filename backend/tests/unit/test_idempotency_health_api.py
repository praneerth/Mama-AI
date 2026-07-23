import unittest
from unittest.mock import patch

from app.api.health import (
    _idempotency_status,
    idempotency_health,
)


HEALTH_SUMMARY = {
    "total": 3,
    "counts": {
        "processing": 1,
        "completed": 1,
        "failed": 1,
    },
    "expired": 0,
    "stuck_processing": 0,
    "stuck_after_seconds": 300,
    "oldest_processing_at": (
        "2026-07-22T10:00:00+00:00"
    ),
    "checked_at": (
        "2026-07-22T10:01:00+00:00"
    ),
}


MAINTENANCE = {
    "enabled": True,
    "running": True,
    "interval_seconds": 300,
    "cleanup_batch_size": 1000,
    "runs": 1,
    "total_deleted": 2,
    "last_deleted": 2,
    "last_run_at": (
        "2026-07-22T10:00:00+00:00"
    ),
    "last_success_at": (
        "2026-07-22T10:00:00+00:00"
    ),
    "last_error": None,
}


class TestIdempotencyHealthAPI(
    unittest.TestCase
):

    @patch(
        "app.api.health."
        "idempotency_maintenance.snapshot"
    )
    @patch(
        "app.api.health."
        "idempotency_store.health_summary"
    )
    def test_healthy_idempotency(
        self,
        mock_summary,
        mock_snapshot,
    ) -> None:
        mock_summary.return_value = dict(
            HEALTH_SUMMARY
        )
        mock_snapshot.return_value = dict(
            MAINTENANCE
        )

        response = _idempotency_status()

        self.assertEqual(
            response["status"],
            "healthy",
        )
        self.assertTrue(
            response["available"]
        )
        self.assertEqual(
            response["counts"][
                "completed"
            ],
            1,
        )

    @patch(
        "app.api.health."
        "idempotency_maintenance.snapshot"
    )
    @patch(
        "app.api.health."
        "idempotency_store.health_summary"
    )
    def test_stuck_processing_is_degraded(
        self,
        mock_summary,
        mock_snapshot,
    ) -> None:
        summary = dict(
            HEALTH_SUMMARY
        )
        summary[
            "stuck_processing"
        ] = 1

        mock_summary.return_value = (
            summary
        )
        mock_snapshot.return_value = dict(
            MAINTENANCE
        )

        response = _idempotency_status()

        self.assertEqual(
            response["status"],
            "degraded",
        )

    @patch(
        "app.api.health."
        "idempotency_maintenance.snapshot"
    )
    @patch(
        "app.api.health."
        "idempotency_store.health_summary"
    )
    def test_stopped_maintenance_is_degraded(
        self,
        mock_summary,
        mock_snapshot,
    ) -> None:
        maintenance = dict(
            MAINTENANCE
        )
        maintenance["running"] = False

        mock_summary.return_value = dict(
            HEALTH_SUMMARY
        )
        mock_snapshot.return_value = (
            maintenance
        )

        response = _idempotency_status()

        self.assertEqual(
            response["status"],
            "degraded",
        )

    @patch(
        "app.api.health."
        "idempotency_maintenance.snapshot"
    )
    @patch(
        "app.api.health."
        "idempotency_store.health_summary",
        side_effect=RuntimeError(
            "database unavailable"
        ),
    )
    def test_storage_failure_is_unavailable(
        self,
        mock_summary,
        mock_snapshot,
    ) -> None:
        mock_snapshot.return_value = dict(
            MAINTENANCE
        )

        response = _idempotency_status()

        self.assertEqual(
            response["status"],
            "unavailable",
        )
        self.assertFalse(
            response["available"]
        )

    @patch(
        "app.api.health._idempotency_status"
    )
    def test_endpoint_returns_status(
        self,
        mock_status,
    ) -> None:
        mock_status.return_value = {
            "status": "healthy",
            "available": True,
        }

        response = idempotency_health()

        self.assertEqual(
            response["status"],
            "healthy",
        )


if __name__ == "__main__":
    unittest.main()
