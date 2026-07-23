import unittest
from datetime import datetime, timedelta, timezone

from app.core.two_factor import (
    build_otpauth_uri,
    derive_totp_secret,
    fingerprint_recovery_code,
    generate_recovery_codes,
    generate_totp_code,
    generate_two_factor_salt,
    normalize_recovery_code,
    verify_totp_code,
)


class TestTwoFactorPrimitives(unittest.TestCase):
    KEY = "mama-two-factor-test-key-" + ("k" * 48)
    USER_ID = "user-123"

    def test_secret_derivation_is_stable_and_user_scoped(self) -> None:
        salt = generate_two_factor_salt()
        first = derive_totp_secret(
            server_key=self.KEY,
            user_id=self.USER_ID,
            salt=salt,
        )
        second = derive_totp_secret(
            server_key=self.KEY,
            user_id=self.USER_ID,
            salt=salt,
        )
        other = derive_totp_secret(
            server_key=self.KEY,
            user_id="user-456",
            salt=salt,
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_known_rfc_totp_vector(self) -> None:
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        code = generate_totp_code(
            secret,
            counter=1,
            digits=8,
        )
        self.assertEqual(code, "94287082")

    def test_verification_accepts_window_and_rejects_replay(self) -> None:
        secret = derive_totp_secret(
            server_key=self.KEY,
            user_id=self.USER_ID,
            salt=generate_two_factor_salt(),
        )
        current = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        previous = current - timedelta(seconds=30)
        code = generate_totp_code(secret, at=previous)
        counter = verify_totp_code(secret, code, at=current, window=1)
        self.assertIsNotNone(counter)
        self.assertIsNone(
            verify_totp_code(
                secret,
                code,
                at=current,
                window=1,
                last_counter=counter,
            )
        )

    def test_recovery_codes_are_unique_and_normalized(self) -> None:
        codes = generate_recovery_codes(10)
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertEqual(len(normalize_recovery_code(code)), 16)

    def test_recovery_fingerprint_ignores_formatting(self) -> None:
        code = generate_recovery_codes(5)[0]
        compact = code.replace("-", "")
        self.assertEqual(
            fingerprint_recovery_code(code),
            fingerprint_recovery_code(compact.lower()),
        )

    def test_otpauth_uri_contains_standard_parameters(self) -> None:
        uri = build_otpauth_uri(
            secret="JBSWY3DPEHPK3PXP",
            account_name="praneeth@example.com",
            issuer="Mama AI",
        )
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("issuer=Mama+AI", uri)
        self.assertIn("digits=6", uri)
        self.assertIn("period=30", uri)

    def test_short_server_key_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            derive_totp_secret(
                server_key="short",
                user_id=self.USER_ID,
                salt=generate_two_factor_salt(),
            )


if __name__ == "__main__":
    unittest.main()
