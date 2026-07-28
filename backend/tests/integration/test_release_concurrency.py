import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.database.idempotency_db import SQLiteIdempotencyStore
from app.database.queue_db import SQLiteTaskQueueStore


class TestReleaseConcurrency(unittest.TestCase):
    def test_concurrent_idempotency_reservations_create_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteIdempotencyStore(Path(directory) / "idempotency.db")
            barrier = threading.Barrier(12)

            def reserve(_index: int) -> dict:
                barrier.wait(timeout=10)
                return store.reserve(
                    idempotency_key="release-concurrency-key-0001",
                    owner_id="release-user",
                    request_method="POST",
                    request_path="/chat",
                    request_payload={"message": "open notepad"},
                    expiry_seconds=3600,
                )

            with ThreadPoolExecutor(max_workers=12) as executor:
                records = list(executor.map(reserve, range(12)))

            self.assertEqual(sum(bool(record["created"]) for record in records), 1)
            self.assertEqual(len({record["record_id"] for record in records}), 1)
            self.assertEqual(store.count(owner_id="release-user"), 1)

    def test_concurrent_workers_claim_each_task_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = SQLiteTaskQueueStore(Path(directory) / "queue.db")
            task_count = 16
            for index in range(task_count):
                queue.enqueue(
                    f"release-task-{index:02d}",
                    owner_id="release-user",
                )

            barrier = threading.Barrier(task_count)

            def claim_and_complete(index: int) -> str:
                worker = f"release-worker-{index:02d}"
                barrier.wait(timeout=10)
                claimed = queue.claim_next(worker_id=worker, lease_seconds=30)
                self.assertIsNotNone(claimed)
                queue.complete(claimed["task_id"], worker_id=worker)
                return str(claimed["task_id"])

            with ThreadPoolExecutor(max_workers=task_count) as executor:
                claimed_ids = list(executor.map(claim_and_complete, range(task_count)))

            self.assertEqual(len(set(claimed_ids)), task_count)
            self.assertEqual(
                len(
                    queue.list(
                        status="completed",
                        owner_id="release-user",
                        limit=task_count + 1,
                    )
                ),
                task_count,
            )
            self.assertIsNone(queue.claim_next(worker_id="final-worker"))
