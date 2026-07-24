import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.metrics import router as metrics_router
from app.config import settings
from app.middleware.request_logger import RequestLoggerMiddleware
from app.observability.metrics import metrics_registry


app = FastAPI()
app.add_middleware(RequestLoggerMiddleware)
app.include_router(metrics_router)


RUNTIME = {
    "runtime_started": True,
    "worker_running": True,
    "database": {"available": True, "latency_ms": 1.0, "error_category": None},
    "queue": {
        "available": True,
        "total": 0,
        "counts": {"failed": 0},
        "stale_claimed": 0,
        "attempts": 0,
        "possibly_truncated": False,
        "error_category": None,
    },
}


class TestObservabilityHTTP(unittest.TestCase):
    TOKEN = "mama-observability-integration-" + ("x" * 48)

    def setUp(self):
        metrics_registry.reset()
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "AUTH_OWNER_ID", "local-user"),
            patch.object(settings, "AUTH_TOKEN", self.TOKEN),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", True),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def headers(self):
        return {"Authorization": "Bearer " + self.TOKEN}

    def test_metrics_requires_authentication(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 401)

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "user")
    def test_normal_user_cannot_read_metrics(self):
        response = self.client.get("/metrics", headers=self.headers())
        self.assertEqual(response.status_code, 403)

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "auditor,user")
    @patch("app.api.metrics.collect_runtime_metrics", return_value=RUNTIME)
    def test_auditor_receives_prometheus_output(self, mock_collect):
        metrics_registry.increment("mama_ai_sample_total")
        response = self.client.get("/metrics", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn("# TYPE mama_ai_sample_total counter", response.text)
        self.assertIn("text/plain", response.headers["content-type"])

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "admin,user")
    @patch("app.api.metrics.collect_runtime_metrics", return_value=RUNTIME)
    def test_admin_receives_alert_summary(self, mock_collect):
        response = self.client.get("/health/observability", headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertIn("metrics", response.json())

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "auditor,user")
    @patch("app.api.metrics.collect_runtime_metrics", return_value=RUNTIME)
    def test_request_id_is_preserved_when_safe(self, mock_collect):
        response = self.client.get(
            "/health/observability",
            headers={**self.headers(), "X-Request-ID": "client-request-1234"},
        )
        self.assertEqual(response.headers["X-Request-ID"], "client-request-1234")

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "auditor,user")
    @patch("app.api.metrics.collect_runtime_metrics", return_value=RUNTIME)
    def test_unsafe_request_id_is_replaced(self, mock_collect):
        response = self.client.get(
            "/health/observability",
            headers={**self.headers(), "X-Request-ID": "bad id with spaces"},
        )
        self.assertNotEqual(response.headers["X-Request-ID"], "bad id with spaces")
        self.assertGreaterEqual(len(response.headers["X-Request-ID"]), 8)


if __name__ == "__main__":
    unittest.main()
