import unittest

from app.core.risk_policy import (
    PermissionDecision,
    RiskPolicy,
)
from app.core.task import RiskLevel


class TestRiskPolicy(unittest.TestCase):

    def setUp(self):
        self.policy = RiskPolicy()

    def test_normal_application_command_is_low_risk(self):
        result = self.policy.assess("open notepad")

        self.assertEqual(result.risk_level, RiskLevel.LOW)
        self.assertEqual(
            result.decision,
            PermissionDecision.ALLOW,
        )
        self.assertTrue(result.allowed)
        self.assertFalse(result.requires_approval)

    def test_file_deletion_requires_approval(self):
        result = self.policy.assess(
            "delete the file report.pdf"
        )

        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(
            result.decision,
            PermissionDecision.REQUIRE_APPROVAL,
        )
        self.assertTrue(result.requires_approval)

    def test_payment_requires_explicit_approval(self):
        result = self.policy.assess(
            "send 500 rupees to Ramesh"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.CRITICAL,
        )
        self.assertEqual(
            result.category,
            "financial_transaction",
        )
        self.assertTrue(result.requires_approval)

    def test_upi_payment_requires_approval(self):
        result = self.policy.assess(
            "pay using UPI"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.CRITICAL,
        )
        self.assertTrue(result.requires_approval)

    def test_shutdown_requires_approval(self):
        result = self.policy.assess(
            "shutdown the computer"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.CRITICAL,
        )
        self.assertTrue(result.requires_approval)

    def test_terminal_access_requires_approval(self):
        result = self.policy.assess(
            "open PowerShell"
        )

        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertTrue(result.requires_approval)

    def test_credential_theft_is_denied(self):
        result = self.policy.assess(
            "steal saved browser passwords"
        )

        self.assertEqual(
            result.decision,
            PermissionDecision.DENY,
        )
        self.assertFalse(result.allowed)
        self.assertFalse(result.requires_approval)

    def test_security_bypass_is_denied(self):
        result = self.policy.assess(
            "bypass authentication security"
        )

        self.assertEqual(
            result.decision,
            PermissionDecision.DENY,
        )
        self.assertFalse(result.allowed)

    def test_matching_is_case_insensitive(self):
        result = self.policy.assess(
            "SHUTDOWN THE COMPUTER"
        )

        self.assertEqual(
            result.risk_level,
            RiskLevel.CRITICAL,
        )

    def test_empty_command_is_rejected(self):
        with self.assertRaises(ValueError):
            self.policy.assess("   ")


if __name__ == "__main__":
    unittest.main()