import unittest

from app.core.device_security import (
    API_KEY_PREFIX,
    api_key_reference,
    fingerprint_api_key,
    fingerprint_device_reference,
    generate_api_key,
    normalize_api_key_scopes,
    normalize_ip_address,
    parse_api_key,
)


class TestDeviceSecurityPrimitives(unittest.TestCase):
    def test_generated_api_key_has_versioned_format(self) -> None:
        key_id, raw = generate_api_key()
        parsed_id, normalized = parse_api_key(raw)
        self.assertEqual(parsed_id, key_id)
        self.assertEqual(normalized, raw)
        self.assertTrue(raw.startswith(API_KEY_PREFIX + "."))

    def test_fingerprint_is_stable_and_does_not_equal_raw_key(self) -> None:
        _, raw = generate_api_key()
        first = fingerprint_api_key(raw)
        second = fingerprint_api_key(raw)
        self.assertEqual(first, second)
        self.assertNotEqual(first, raw)
        self.assertEqual(len(first), 64)

    def test_api_key_reference_uses_non_secret_identifier(self) -> None:
        key_id, raw = generate_api_key()
        self.assertEqual(api_key_reference(raw), key_id[:12])

    def test_malformed_key_is_rejected(self) -> None:
        for value in ("", "mamaak1.invalid.secret", "wrong.value.secret"):
            with self.assertRaises((TypeError, ValueError)):
                parse_api_key(value)

    def test_scopes_are_validated_and_sorted(self) -> None:
        scopes = normalize_api_key_scopes(
            ["api.write", "api.read", "api.read"]
        )
        self.assertEqual(scopes, ("api.read", "api.write"))
        with self.assertRaises(ValueError):
            normalize_api_key_scopes(["admin.everything"])

    def test_device_reference_is_domain_separated(self) -> None:
        first = fingerprint_device_reference("device-123")
        second = fingerprint_device_reference("device-123")
        self.assertEqual(first, second)
        self.assertNotEqual(first, "device-123")

    def test_ip_address_is_normalized(self) -> None:
        self.assertEqual(normalize_ip_address("127.0.0.1"), "127.0.0.1")
        self.assertEqual(normalize_ip_address("2001:0db8::1"), "2001:db8::1")
        with self.assertRaises(ValueError):
            normalize_ip_address("not-an-ip")


if __name__ == "__main__":
    unittest.main()
