import unittest
from unittest.mock import patch

from app.database.security_event_db import (
    record_security_event_safely,
)


class TestSafeSecurityEventRecorder(
    unittest.TestCase
):

    @patch(
        "app.database.security_event_db."
        "security_event_store.append"
    )
    def test_successful_record_returns_true(
        self,
        mock_append,
    ) -> None:
        result = record_security_event_safely(
            event_type="invalid_token",
            severity="warning",
        )

        self.assertTrue(result)
        mock_append.assert_called_once()

    @patch(
        "app.database.security_event_db."
        "security_event_store.append",
        side_effect=RuntimeError(
            "Database unavailable"
        ),
    )
    def test_storage_failure_is_fail_open(
        self,
        mock_append,
    ) -> None:
        with self.assertLogs(
            "mama_ai.security_audit",
            level="ERROR",
        ) as captured:
            result = (
                record_security_event_safely(
                    event_type=(
                        "rate_limit_exceeded"
                    ),
                    severity="warning",
                    metadata={
                        "token": (
                            "must-not-be-logged"
                        ),
                    },
                )
            )

        self.assertFalse(result)
        mock_append.assert_called_once()

        combined = "\n".join(
            captured.output
        )

        self.assertIn(
            "RuntimeError",
            combined,
        )
        self.assertNotIn(
            "must-not-be-logged",
            combined,
        )


if __name__ == "__main__":
    unittest.main()
