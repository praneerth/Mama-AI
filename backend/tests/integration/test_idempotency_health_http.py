import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router as health_router
from app.config import settings


app = FastAPI()
app.include_router(health_router)


HEALTHY_IDEMPOTENCY = {
    "status": "healthy",
    "available": True,
    "total": 0,
    "counts": {
        "processing": 0,
        "completed": 0,
        "failed": 0,
    },
    "expired": 0,
    "stuck_processing": 0,
    "maintenance": {
        "enabled": True,
        "running": True,
    },
    "error": None,
}


class TestIdempotencyHealthHTTP(unittest.TestCase):

    TOKEN = "mama-runtime-health-integration-" + ("h" * 48)

    def setUp(self) -> None:
        self.settings_patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "AUTH_OWNER_ID", "local-user"),
            patch.object(settings, "AUTH_TOKEN", self.TOKEN),
            patch.object(
                settings,
                "AUTH_STATIC_COMPATIBILITY_ENABLED",
                True,
            ),
        ]
        for patcher in self.settings_patchers:
            patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self.settings_patchers):
            patcher.stop()

    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.TOKEN}

    @patch("app.api.health._readiness_payload")
    def test_public_readiness_is_redacted(self, mock_readiness) -> None:
        mock_readiness.return_value = {
            "status": "ready",
            "ready": True,
            "app": "Mama AI",
            "version": "1.0.0",
            "checks": {"database": True, "worker_running": True},
            "database": {"path": "secret/runtime.db"},
            "worker": {"worker_id": "private-worker-id"},
            "queue": {"total": 100},
            "idempotency": {"total": 20},
        }
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertNotIn("database", payload)
        self.assertNotIn("worker", payload)
        self.assertNotIn("queue", payload)
        self.assertNotIn("idempotency", payload)

    def test_detailed_health_requires_authentication(self) -> None:
        response = self.client.get("/health/idempotency")
        self.assertEqual(response.status_code, 401)

    @patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ROLES", "user")
    def test_user_role_cannot_read_detailed_health(self) -> None:
        response = self.client.get(
            "/health/idempotency",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "auditor,user",
    )
    @patch("app.api.health._idempotency_status")
    def test_auditor_can_read_idempotency_health(self, mock_status) -> None:
        mock_status.return_value = dict(HEALTHY_IDEMPOTENCY)
        response = self.client.get(
            "/health/idempotency",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ROLES",
        "admin,user",
    )
    @patch("app.api.health._idempotency_status")
    def test_admin_sees_degraded_health(self, mock_status) -> None:
        degraded = dict(HEALTHY_IDEMPOTENCY)
        degraded["status"] = "degraded"
        degraded["stuck_processing"] = 1
        mock_status.return_value = degraded
        response = self.client.get(
            "/health/idempotency",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stuck_processing"], 1)


if __name__ == "__main__":
    unittest.main()
