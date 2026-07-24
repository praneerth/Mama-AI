import unittest
from unittest.mock import patch

from app.config import settings
from app.observability.alerts import evaluate_alerts
from app.observability.metrics import metrics_registry


HEALTHY_RUNTIME = {
    "runtime_started": True,
    "worker_running": True,
    "database": {"available": True},
    "queue": {"counts": {"failed": 0}, "stale_claimed": 0},
}


class TestObservabilityAlerts(unittest.TestCase):
    def setUp(self):
        metrics_registry.reset()

    def test_healthy_runtime_has_no_alerts(self):
        report = evaluate_alerts(HEALTHY_RUNTIME)
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["alert_count"], 0)

    def test_database_failure_is_critical(self):
        runtime = {**HEALTHY_RUNTIME, "database": {"available": False}}
        report = evaluate_alerts(runtime)
        self.assertEqual(report["status"], "critical")
        self.assertEqual(report["alerts"][0]["code"], "database_unavailable")

    def test_stopped_worker_is_critical_after_runtime_start(self):
        runtime = {**HEALTHY_RUNTIME, "worker_running": False}
        report = evaluate_alerts(runtime)
        self.assertEqual(report["status"], "critical")

    @patch.object(settings, "OBSERVABILITY_ALERT_FAILED_QUEUE_JOBS", 2)
    def test_failed_queue_threshold_creates_warning(self):
        runtime = {
            **HEALTHY_RUNTIME,
            "queue": {"counts": {"failed": 2}, "stale_claimed": 0},
        }
        report = evaluate_alerts(runtime)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["alerts"][0]["code"], "failed_queue_jobs")

    @patch.object(settings, "OBSERVABILITY_ALERT_MIN_REQUESTS", 2)
    @patch.object(settings, "OBSERVABILITY_ALERT_ERROR_RATE_PERCENT", 40.0)
    def test_http_server_error_rate_creates_warning(self):
        metrics_registry.increment("mama_ai_http_requests_total", 2)
        metrics_registry.increment(
            "mama_ai_http_errors_total", 1, labels={"category": "server"}
        )
        report = evaluate_alerts(HEALTHY_RUNTIME)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["request_sample"]["server_error_rate_percent"], 50.0)


if __name__ == "__main__":
    unittest.main()
