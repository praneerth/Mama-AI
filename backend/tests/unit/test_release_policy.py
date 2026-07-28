import unittest

from app.release.policy import ReleasePolicy


class TestReleasePolicy(unittest.TestCase):
    def test_defaults_are_strict(self) -> None:
        policy = ReleasePolicy()
        self.assertGreaterEqual(policy.minimum_unit_tests, 500)
        self.assertGreaterEqual(policy.minimum_integration_tests, 100)
        self.assertTrue(policy.require_security_scans)
        self.assertTrue(policy.require_verified_backup)
        self.assertTrue(policy.require_load_test)

    def test_environment_overrides_thresholds(self) -> None:
        policy = ReleasePolicy.from_environment(
            {
                "MAMA_RELEASE_MIN_UNIT_TESTS": "600",
                "MAMA_RELEASE_MAX_LOAD_ERROR_PERCENT": "0.5",
                "MAMA_RELEASE_MAX_LOAD_P95_MS": "750",
                "MAMA_RELEASE_REQUIRE_VERIFIED_BACKUP": "false",
            }
        )
        self.assertEqual(policy.minimum_unit_tests, 600)
        self.assertEqual(policy.maximum_load_error_rate_percent, 0.5)
        self.assertEqual(policy.maximum_load_p95_ms, 750.0)
        self.assertFalse(policy.require_verified_backup)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReleasePolicy.from_environment(
                {"MAMA_RELEASE_REQUIRE_LOAD_TEST": "sometimes"}
            )

    def test_invalid_threshold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReleasePolicy(maximum_load_error_rate_percent=101.0)
        with self.assertRaises(ValueError):
            ReleasePolicy(maximum_load_p95_ms=0.0)
        with self.assertRaises(ValueError):
            ReleasePolicy(minimum_unit_tests=-1)

    def test_policy_serialization_contains_no_secrets(self) -> None:
        serialized = ReleasePolicy().as_dict()
        self.assertNotIn("token", " ".join(serialized).lower())
        self.assertNotIn("password", " ".join(serialized).lower())
