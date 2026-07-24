import json
import logging
import unittest

from app.config.logger import JsonLogFormatter
from app.observability.redaction import REDACTED, redact_text, redact_value


class TestObservabilityRedaction(unittest.TestCase):
    def test_sensitive_mapping_keys_are_redacted(self):
        value = redact_value({
            "password": "secret-password",
            "nested": {"api_key": "raw-key"},
            "safe": "visible",
        })
        self.assertEqual(value["password"], REDACTED)
        self.assertEqual(value["nested"]["api_key"], REDACTED)
        self.assertEqual(value["safe"], "visible")

    def test_bearer_token_is_removed_from_text(self):
        output = redact_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", output)
        self.assertIn(REDACTED, output)

    def test_query_secret_is_removed(self):
        output = redact_text("/callback?token=raw-secret-value&safe=yes")
        self.assertNotIn("raw-secret-value", output)
        self.assertIn("token=" + REDACTED, output)

    def test_versioned_tokens_are_removed(self):
        output = redact_text("mama1.header.signature mak1.identifier.secretpart")
        self.assertNotIn("signature", output)
        self.assertNotIn("secretpart", output)

    def test_binary_values_are_not_logged_raw(self):
        self.assertEqual(redact_value(b"private-bytes"), "<bytes:13>")

    def test_json_formatter_includes_request_fields(self):
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            "mama_ai.test", logging.INFO, __file__, 1,
            "request complete", (), None,
        )
        record.request_id = "request-1234"
        record.event = "test_event"
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["request_id"], "request-1234")
        self.assertEqual(payload["event"], "test_event")

    def test_json_formatter_redacts_extra_secret(self):
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            "mama_ai.test", logging.INFO, __file__, 1,
            "safe message", (), None,
        )
        record.access_token = "raw-access-token"
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["access_token"], REDACTED)
        self.assertNotIn("raw-access-token", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
