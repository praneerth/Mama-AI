import unittest

from app.middleware.rate_limiter import (
    RateLimitRule,
    SlidingWindowRateLimitStore,
    classify_request,
    fingerprint_value,
    is_rate_limit_exempt,
)


class TestSlidingWindowRateLimitStore(
    unittest.TestCase
):

    def setUp(self) -> None:
        self.store = (
            SlidingWindowRateLimitStore(
                clock=lambda: 0.0
            )
        )

    def test_request_is_blocked_after_limit(
        self,
    ) -> None:
        rule = RateLimitRule(
            name="general",
            limit=2,
            window_seconds=60,
        )

        first = self.store.check_request(
            ["client:a"],
            rule,
            now=10.0,
        )
        second = self.store.check_request(
            ["client:a"],
            rule,
            now=11.0,
        )
        third = self.store.check_request(
            ["client:a"],
            rule,
            now=12.0,
        )

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertEqual(
            third.retry_after,
            58,
        )

    def test_all_identifiers_are_limited(
        self,
    ) -> None:
        rule = RateLimitRule(
            name="chat",
            limit=1,
            window_seconds=60,
        )

        first = self.store.check_request(
            [
                "client:a",
                "token:x",
            ],
            rule,
            now=1.0,
        )

        second = self.store.check_request(
            [
                "client:b",
                "token:x",
            ],
            rule,
            now=2.0,
        )

        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)

    def test_window_expiry_allows_request(
        self,
    ) -> None:
        rule = RateLimitRule(
            name="general",
            limit=1,
            window_seconds=10,
        )

        self.store.check_request(
            ["client:a"],
            rule,
            now=5.0,
        )

        result = self.store.check_request(
            ["client:a"],
            rule,
            now=15.0,
        )

        self.assertTrue(result.allowed)

    def test_authentication_threshold_starts_cooldown(
        self,
    ) -> None:
        first = (
            self.store.record_authentication_failure(
                "client:a",
                failure_limit=2,
                failure_window_seconds=60,
                cooldown_seconds=300,
                now=10.0,
            )
        )

        second = (
            self.store.record_authentication_failure(
                "client:a",
                failure_limit=2,
                failure_window_seconds=60,
                cooldown_seconds=300,
                now=11.0,
            )
        )

        self.assertFalse(first.blocked)
        self.assertTrue(second.blocked)
        self.assertEqual(
            second.retry_after,
            300,
        )

    def test_authentication_cooldown_expires(
        self,
    ) -> None:
        self.store.record_authentication_failure(
            "client:a",
            failure_limit=1,
            failure_window_seconds=60,
            cooldown_seconds=10,
            now=20.0,
        )

        active = (
            self.store.authentication_cooldown(
                "client:a",
                now=25.0,
            )
        )

        expired = (
            self.store.authentication_cooldown(
                "client:a",
                now=30.0,
            )
        )

        self.assertTrue(active.blocked)
        self.assertEqual(
            active.retry_after,
            5,
        )
        self.assertFalse(expired.blocked)

    def test_reset_clears_state(
        self,
    ) -> None:
        rule = RateLimitRule(
            name="general",
            limit=1,
            window_seconds=60,
        )

        self.store.check_request(
            ["client:a"],
            rule,
            now=1.0,
        )

        self.store.reset()

        result = self.store.check_request(
            ["client:a"],
            rule,
            now=2.0,
        )

        self.assertTrue(result.allowed)


class TestRateLimitClassification(
    unittest.TestCase
):

    def test_sensitive_categories(
        self,
    ) -> None:
        self.assertEqual(
            classify_request(
                "POST",
                "/chat",
            ),
            "chat",
        )

        self.assertEqual(
            classify_request(
                "POST",
                "/memory",
            ),
            "memory_write",
        )

        self.assertEqual(
            classify_request(
                "POST",
                "/tasks/abc/retry",
            ),
            "sensitive_action",
        )

        self.assertEqual(
            classify_request(
                "POST",
                "/approvals/abc/reject",
            ),
            "sensitive_action",
        )

    def test_health_and_options_are_exempt(
        self,
    ) -> None:
        self.assertTrue(
            is_rate_limit_exempt(
                "GET",
                "/health/runtime",
            )
        )

        self.assertTrue(
            is_rate_limit_exempt(
                "OPTIONS",
                "/chat",
            )
        )

        self.assertFalse(
            is_rate_limit_exempt(
                "GET",
                "/tasks",
            )
        )

    def test_fingerprint_does_not_expose_value(
        self,
    ) -> None:
        secret = (
            "this-is-a-private-bearer-token"
        )

        fingerprint = fingerprint_value(
            secret,
            namespace="bearer",
        )

        self.assertNotEqual(
            fingerprint,
            secret,
        )
        self.assertNotIn(
            secret,
            fingerprint,
        )
        self.assertEqual(
            len(fingerprint),
            24,
        )


if __name__ == "__main__":
    unittest.main()
