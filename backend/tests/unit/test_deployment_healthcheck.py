from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.deployment.healthcheck import check, readiness_url


class TestDeploymentHealthcheck(unittest.TestCase):
    def test_ready_payload_passes(self):
        body = json.dumps({"status": "ready", "ready": True}).encode("utf-8")
        with patch(
            "app.deployment.healthcheck._perform_get",
            return_value=(200, body),
        ):
            self.assertTrue(check("http://example/health/ready"))

    def test_non_ready_payload_fails(self):
        body = json.dumps(
            {"status": "not_ready", "ready": False}
        ).encode("utf-8")
        with patch(
            "app.deployment.healthcheck._perform_get",
            return_value=(200, body),
        ):
            self.assertFalse(check("http://example/health/ready"))

    def test_invalid_json_fails_closed(self):
        with patch(
            "app.deployment.healthcheck._perform_get",
            return_value=(200, b"not-json"),
        ):
            self.assertFalse(check("http://example/health/ready"))

    def test_non_http_scheme_is_rejected(self):
        self.assertFalse(check("file:///etc/passwd"))

    def test_credentials_are_rejected(self):
        self.assertFalse(check("http://user:secret@example/health/ready"))

    def test_non_positive_timeout_is_rejected(self):
        self.assertFalse(check("http://example/health/ready", timeout=0))

    def test_url_uses_configured_port(self):
        with patch.dict(
            "os.environ",
            {"PORT": "8123", "MAMA_HEALTHCHECK_HOST": "localhost"},
        ):
            self.assertEqual(
                readiness_url(),
                "http://localhost:8123/health/ready",
            )


if __name__ == "__main__":
    unittest.main()
