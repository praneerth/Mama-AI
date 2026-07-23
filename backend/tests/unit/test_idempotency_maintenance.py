import unittest

from app.core.idempotency_maintenance import (
    IdempotencyMaintenanceWorker,
)


class FakeStore:

    def __init__(
        self,
        *,
        deleted: int = 0,
        error: Exception | None = None,
    ) -> None:
        self.deleted = deleted
        self.error = error
        self.calls: list[int] = []

    def delete_expired(
        self,
        *,
        limit: int,
    ) -> int:
        self.calls.append(limit)

        if self.error is not None:
            raise self.error

        return self.deleted


class TestIdempotencyMaintenanceWorker(
    unittest.TestCase
):

    def test_run_once_deletes_expired_records(
        self,
    ) -> None:
        store = FakeStore(
            deleted=4
        )
        worker = (
            IdempotencyMaintenanceWorker(
                store=store,
                interval_seconds=60,
                cleanup_batch_size=25,
            )
        )

        report = worker.run_once()
        snapshot = worker.snapshot()

        self.assertTrue(
            report["success"]
        )
        self.assertEqual(
            report["deleted"],
            4,
        )
        self.assertEqual(
            store.calls,
            [25],
        )
        self.assertEqual(
            snapshot["total_deleted"],
            4,
        )

    def test_cleanup_failure_is_recorded(
        self,
    ) -> None:
        store = FakeStore(
            error=RuntimeError(
                "database unavailable"
            )
        )
        worker = (
            IdempotencyMaintenanceWorker(
                store=store,
                interval_seconds=60,
            )
        )

        with self.assertLogs(
            "mama_ai.idempotency_maintenance",
            level="ERROR",
        ):
            report = worker.run_once()

        self.assertFalse(
            report["success"]
        )
        self.assertIn(
            "RuntimeError",
            worker.snapshot()[
                "last_error"
            ],
        )

    def test_start_runs_cleanup_and_starts_thread(
        self,
    ) -> None:
        store = FakeStore(
            deleted=2
        )
        worker = (
            IdempotencyMaintenanceWorker(
                store=store,
                interval_seconds=60,
            )
        )

        started = worker.start()

        self.assertTrue(started)
        self.assertTrue(worker.running)
        self.assertEqual(
            store.calls,
            [1000],
        )
        self.assertTrue(
            worker.stop(timeout=2)
        )
        self.assertFalse(worker.running)

    def test_start_is_idempotent(
        self,
    ) -> None:
        worker = (
            IdempotencyMaintenanceWorker(
                store=FakeStore(),
                interval_seconds=60,
            )
        )

        self.assertTrue(worker.start())
        self.assertFalse(worker.start())
        self.assertTrue(
            worker.stop(timeout=2)
        )

    def test_disabled_worker_does_not_start(
        self,
    ) -> None:
        store = FakeStore()
        worker = (
            IdempotencyMaintenanceWorker(
                store=store,
                enabled=False,
                interval_seconds=60,
            )
        )

        self.assertFalse(worker.start())
        self.assertFalse(worker.running)
        self.assertEqual(
            store.calls,
            [],
        )

    def test_invalid_cleanup_batch_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            IdempotencyMaintenanceWorker(
                store=FakeStore(),
                cleanup_batch_size=1001,
            )


if __name__ == "__main__":
    unittest.main()
