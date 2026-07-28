import threading
import unittest

from app.release.load import LoadTestConfig, run_load_test


class IncrementingClock:
    def __init__(self, step: float = 0.01) -> None:
        self.value = 0.0
        self.step = step
        self.lock = threading.Lock()

    def __call__(self) -> float:
        with self.lock:
            current = self.value
            self.value += self.step
            return current


class TestReleaseLoad(unittest.TestCase):
    def test_successful_load_run_passes(self) -> None:
        result = run_load_test(
            LoadTestConfig(
                url="http://127.0.0.1:8000/health/ready",
                requests=20,
                concurrency=4,
                maximum_p95_ms=1000.0,
            ),
            requester=lambda _config: 200,
            clock=IncrementingClock(0.001),
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.total_requests, 20)
        self.assertEqual(result.successful_requests, 20)
        self.assertEqual(result.status_counts, {"200": 20})
        self.assertEqual(result.error_counts, {})

    def test_http_errors_are_counted_without_response_bodies(self) -> None:
        counter = 0
        lock = threading.Lock()

        def requester(_config: LoadTestConfig) -> int:
            nonlocal counter
            with lock:
                counter += 1
                return 503 if counter <= 2 else 200

        result = run_load_test(
            LoadTestConfig(
                url="http://service/health",
                requests=10,
                concurrency=2,
                maximum_error_rate_percent=1.0,
            ),
            requester=requester,
            clock=IncrementingClock(0.001),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.failed_requests, 2)
        self.assertEqual(result.error_counts, {"HTTP_503": 2})
        self.assertNotIn("body", result.as_dict())

    def test_exception_names_are_aggregated(self) -> None:
        result = run_load_test(
            LoadTestConfig(
                url="http://service/health",
                requests=3,
                concurrency=1,
            ),
            requester=lambda _config: (_ for _ in ()).throw(TimeoutError()),
            clock=IncrementingClock(0.001),
        )
        self.assertEqual(result.error_counts, {"TimeoutError": 3})
        self.assertEqual(result.status_counts, {})
        self.assertFalse(result.passed)

    def test_latency_threshold_can_fail_release(self) -> None:
        result = run_load_test(
            LoadTestConfig(
                url="http://service/health",
                requests=5,
                concurrency=1,
                maximum_p95_ms=5.0,
            ),
            requester=lambda _config: 200,
            clock=IncrementingClock(0.01),
        )
        self.assertGreater(result.p95_ms, 5.0)
        self.assertFalse(result.passed)

    def test_configuration_validation(self) -> None:
        with self.assertRaises(ValueError):
            LoadTestConfig(url="", requests=1, concurrency=1)
        with self.assertRaises(ValueError):
            LoadTestConfig(url="http://x", requests=1, concurrency=2)
        with self.assertRaises(ValueError):
            LoadTestConfig(url="http://x", method="DELETE")
        with self.assertRaises(ValueError):
            LoadTestConfig(url="file:///etc/passwd")
        with self.assertRaises(ValueError):
            LoadTestConfig(url="http://user:secret@example/health")
        with self.assertRaises(ValueError):
            LoadTestConfig(url="http://example:invalid/health")

    def test_query_parameters_are_removed_from_result(self) -> None:
        result = run_load_test(
            LoadTestConfig(
                url="https://service.example/health?token=secret#fragment",
                requests=1,
                concurrency=1,
            ),
            requester=lambda _config: 200,
            clock=IncrementingClock(0.001),
        )
        self.assertEqual(result.url, "https://service.example/health")
        self.assertNotIn("secret", str(result.as_dict()))

    def test_headers_are_not_serialized(self) -> None:
        config = LoadTestConfig(
            url="http://service/auth/me",
            requests=1,
            concurrency=1,
            headers={"Authorization": "Bearer secret-value"},
        )
        result = run_load_test(
            config,
            requester=lambda _config: 200,
            clock=IncrementingClock(0.001),
        )
        encoded = str(result.as_dict())
        self.assertNotIn("secret-value", encoded)
        self.assertNotIn("Authorization", encoded)
