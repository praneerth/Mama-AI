import tempfile
import unittest
from pathlib import Path

from app.core.approval_registry import (
    ApprovalRegistry,
)
from app.core.runtime_state import (
    RuntimeStateManager,
)
from app.core.task_registry import (
    TaskRegistry,
)
from app.database.state_db import (
    SQLiteStateStore,
)


class FakeWorker:

    def __init__(
        self,
        events: list[str] | None = None,
        *,
        name: str = "worker",
        start_error: Exception | None = None,
    ) -> None:
        self._running = False
        self.events = events
        self.name = name
        self.start_error = start_error
        self.start_calls = 0
        self.stop_calls = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        self.start_calls += 1

        if self.events is not None:
            self.events.append(
                f"{self.name}_start"
            )

        if self.start_error is not None:
            raise self.start_error

        if self._running:
            return False

        self._running = True
        return True

    def stop(
        self,
        *,
        timeout: float = 5.0,
    ) -> bool:
        self.stop_calls += 1
        self._running = False

        if self.events is not None:
            self.events.append(
                f"{self.name}_stop"
            )

        return True


class FakeReconciler:

    def __init__(
        self,
        events: list[str],
    ) -> None:
        self.events = events

    def reconcile(self) -> dict:
        self.events.append(
            "reconcile"
        )
        return {
            "changes": 0,
        }


class TestRuntimeIdempotencyMaintenance(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.store = SQLiteStateStore(
            Path(
                self.temp_directory.name
            )
            / "runtime-maintenance.db"
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def manager(
        self,
        *,
        worker=None,
        maintenance=None,
        reconciler=None,
    ) -> RuntimeStateManager:
        return RuntimeStateManager(
            tasks=TaskRegistry(),
            approvals=ApprovalRegistry(),
            store=self.store,
            worker=worker,
            reconciler=reconciler,
            maintenance_worker=(
                maintenance
            ),
        )

    def test_maintenance_lifecycle_is_managed(
        self,
    ) -> None:
        maintenance = FakeWorker(
            name="maintenance"
        )
        manager = self.manager(
            maintenance=maintenance
        )

        started = manager.start()

        self.assertTrue(
            started[
                "maintenance_started"
            ]
        )
        self.assertTrue(
            started[
                "maintenance_running"
            ]
        )

        stopped = manager.stop()

        self.assertTrue(
            stopped[
                "maintenance_stopped"
            ]
        )
        self.assertEqual(
            maintenance.stop_calls,
            1,
        )

    def test_maintenance_starts_after_task_worker(
        self,
    ) -> None:
        events: list[str] = []
        worker = FakeWorker(
            events,
            name="worker",
        )
        maintenance = FakeWorker(
            events,
            name="maintenance",
        )
        reconciler = FakeReconciler(
            events
        )

        manager = self.manager(
            worker=worker,
            maintenance=maintenance,
            reconciler=reconciler,
        )

        manager.start()

        self.assertEqual(
            events[:3],
            [
                "reconcile",
                "worker_start",
                "maintenance_start",
            ],
        )

        manager.stop()

    def test_maintenance_start_failure_stops_worker(
        self,
    ) -> None:
        worker = FakeWorker(
            name="worker"
        )
        maintenance = FakeWorker(
            name="maintenance",
            start_error=RuntimeError(
                "maintenance failed"
            ),
        )
        manager = self.manager(
            worker=worker,
            maintenance=maintenance,
        )

        with self.assertRaises(
            RuntimeError
        ):
            manager.start()

        self.assertFalse(worker.running)
        self.assertEqual(
            worker.stop_calls,
            1,
        )
        self.assertFalse(
            manager.started
        )


if __name__ == "__main__":
    unittest.main()
