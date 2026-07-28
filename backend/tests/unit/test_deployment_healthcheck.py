from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from app.deployment.healthcheck import check, readiness_url


class _Response:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body.read()


class TestDeploymentHealthcheck(unittest.TestCase):
    def test_ready_payload_passes(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_Response(200, {"status": "ready", "ready": True}),
        ):
            self.assertTrue(check("http://example/health/ready"))

    def test_non_ready_payload_fails(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_Response(200, {"status": "not_ready", "ready": False}),
        ):
            self.assertFalse(check("http://example/health/ready"))

    def test_invalid_json_fails_closed(self):
        response = _Response(200, {})
        response._body = io.BytesIO(b"not-json")
        with patch("urllib.request.urlopen", return_value=response):
            self.assertFalse(check("http://example/health/ready"))

    def test_url_uses_configured_port(self):
        with patch.dict("os.environ", {"PORT": "8123", "MAMA_HEALTHCHECK_HOST": "localhost"}):
            self.assertEqual(readiness_url(), "http://localhost:8123/health/ready")


if __name__ == "__main__":
    unittest.main()
