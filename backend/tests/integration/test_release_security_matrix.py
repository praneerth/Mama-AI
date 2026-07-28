import sys
import types
import unittest
from unittest.mock import patch

try:
    from google import genai as _genai  # noqa: F401
except ImportError:
    import google

    genai_stub = types.ModuleType("google.genai")

    class _Client:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Gemini is not used by release security tests.")

    genai_stub.Client = _Client
    google.genai = genai_stub
    sys.modules["google.genai"] = genai_stub

from fastapi.testclient import TestClient

from app.config import settings
from app.middleware import rate_limit_store
from main import app


class TestReleaseSecurityMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "AUTH_TOKEN", "mama-release-" + ("a" * 48)),
            patch.object(settings, "RATE_LIMIT_ENABLED", False),
        ]
        for patcher in self.patchers:
            patcher.start()
        rate_limit_store.reset()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_public_probes_remain_available(self) -> None:
        for path in ("/health", "/health/ready"):
            response = self.client.get(path)
            self.assertIn(response.status_code, {200, 503}, path)
            self.assertNotEqual(response.status_code, 401, path)

    def test_operational_and_user_data_routes_require_authentication(self) -> None:
        protected_paths = (
            "/auth/me",
            "/history",
            "/queue",
            "/tasks",
            "/security/events",
            "/metrics",
            "/health/runtime",
            "/admin/database/status",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_invalid_token_is_not_reflected(self) -> None:
        invalid = "invalid-release-token-value"
        response = self.client.get(
            "/history",
            headers={"Authorization": f"Bearer {invalid}"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(invalid, response.text)
