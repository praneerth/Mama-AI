import unittest
from unittest.mock import patch

from app.observability.metrics import metrics_registry
from app.observability.runtime import collect_queue_metrics, collect_runtime_metrics


class TestObservabilityRuntime(unittest.TestCase):
    def setUp(self):
        metrics_registry.reset()

    @patch("app.observability.runtime.task_queue_store.list")
    def test_queue_metrics_count_statuses_attempts_and_stale_claims(self, mock_list):
        mock_list.return_value = [
            {"status": "queued", "attempts": 0, "lease_expires_at": None},
            {"status": "failed", "attempts": 3, "lease_expires_at": None},
            {"status": "claimed", "attempts": 1, "lease_expires_at": "2000-01-01T00:00:00+00:00"},
        ]
        report = collect_queue_metrics()
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual(report["attempts"], 4)
        self.assertEqual(report["stale_claimed"], 1)
        self.assertEqual(
            metrics_registry.gauge_value("mama_ai_queue_jobs", labels={"status": "failed"}),
            1,
        )

    @patch("app.observability.runtime.task_queue_store.list", side_effect=RuntimeError("private detail"))
    def test_queue_probe_exposes_only_error_category(self, mock_list):
        report = collect_queue_metrics()
        self.assertFalse(report["available"])
        self.assertEqual(report["error_category"], "RuntimeError")
        self.assertNotIn("private detail", repr(report))

    @patch("app.observability.runtime.collect_queue_metrics")
    @patch("app.observability.runtime.collect_database_metrics")
    @patch("app.observability.runtime.task_worker")
    @patch("app.observability.runtime.runtime_state")
    def test_runtime_metrics_publish_worker_and_runtime_gauges(
        self, mock_runtime, mock_worker, mock_database, mock_queue
    ):
        mock_runtime.started = True
        mock_worker.running = False
        mock_database.return_value = {"available": True, "latency_ms": 1, "error_category": None}
        mock_queue.return_value = {"available": True, "counts": {}, "stale_claimed": 0}
        report = collect_runtime_metrics()
        self.assertTrue(report["runtime_started"])
        self.assertFalse(report["worker_running"])
        self.assertEqual(metrics_registry.gauge_value("mama_ai_runtime_started"), 1)
        self.assertEqual(metrics_registry.gauge_value("mama_ai_worker_running"), 0)


if __name__ == "__main__":
    unittest.main()
