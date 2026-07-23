import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from main import app


class TestIdempotencyHealthHTTP(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    @patch(
        "app.api.health._idempotency_status"
    )
    def test_health_endpoint_is_public(
        self,
        mock_status,
    ) -> None:
        mock_status.return_value = {
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

        response = self.client.get(
            "/health/idempotency"
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["status"],
            "healthy",
        )

    @patch(
        "app.api.health._idempotency_status"
    )
    def test_degraded_health_is_reported(
        self,
        mock_status,
    ) -> None:
        mock_status.return_value = {
            "status": "degraded",
            "available": True,
            "total": 1,
            "counts": {
                "processing": 1,
                "completed": 0,
                "failed": 0,
            },
            "expired": 0,
            "stuck_processing": 1,
            "maintenance": {
                "enabled": True,
                "running": True,
            },
            "error": None,
        }

        response = self.client.get(
            "/health/idempotency"
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "stuck_processing"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
