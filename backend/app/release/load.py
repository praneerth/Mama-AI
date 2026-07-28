"""Small, dependency-free HTTP concurrency test used as a release gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPSConnection
from math import ceil
from time import perf_counter
from typing import Callable, Mapping
import urllib.error
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class LoadTestConfig:
    url: str
    requests: int = 100
    concurrency: int = 10
    timeout_seconds: float = 5.0
    expected_status: int = 200
    maximum_error_rate_percent: float = 1.0
    maximum_p95_ms: float = 1000.0
    method: str = "GET"
    headers: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    body: bytes | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.url or not self.url.strip():
            raise ValueError("Load-test URL is required.")
        parsed_url = urlsplit(self.url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("Load-test URL must use http or https.")
        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError("Load-test URL must not include credentials.")
        try:
            parsed_url.port
        except ValueError as exc:
            raise ValueError("Load-test URL contains an invalid port.") from exc
        if self.requests < 1:
            raise ValueError("Load-test requests must be at least 1.")
        if self.concurrency < 1:
            raise ValueError("Load-test concurrency must be at least 1.")
        if self.concurrency > self.requests:
            raise ValueError("Concurrency cannot exceed request count.")
        if self.timeout_seconds <= 0:
            raise ValueError("Load-test timeout must be greater than zero.")
        if not 100 <= self.expected_status <= 599:
            raise ValueError("Expected HTTP status is invalid.")
        if not 0.0 <= self.maximum_error_rate_percent <= 100.0:
            raise ValueError("Maximum error rate must be between 0 and 100.")
        if self.maximum_p95_ms <= 0:
            raise ValueError("Maximum p95 latency must be greater than zero.")
        normalized_method = self.method.strip().upper()
        if normalized_method not in {"GET", "HEAD", "POST"}:
            raise ValueError("Load-test method must be GET, HEAD, or POST.")
        object.__setattr__(self, "method", normalized_method)


@dataclass(frozen=True)
class RequestSample:
    status_code: int | None
    duration_ms: float
    error_type: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_type is None


@dataclass(frozen=True)
class LoadTestResult:
    url: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_percent: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    maximum_ms: float
    status_counts: dict[str, int]
    error_counts: dict[str, int]
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate_percent": self.error_rate_percent,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "maximum_ms": self.maximum_ms,
            "status_counts": dict(self.status_counts),
            "error_counts": dict(self.error_counts),
            "passed": self.passed,
        }


Requester = Callable[[LoadTestConfig], int]


def _default_requester(config: LoadTestConfig) -> int:
    parsed = urlsplit(config.url)
    connection_type = (
        HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    )
    connection = connection_type(
        parsed.hostname,
        parsed.port,
        timeout=config.timeout_seconds,
    )
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request(
            config.method,
            target,
            body=config.body,
            headers={
                "User-Agent": "mama-ai-release-load/1",
                **dict(config.headers),
            },
        )
        response = connection.getresponse()
        response.read(1)
        return int(response.status)
    finally:
        connection.close()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil((percentile / 100.0) * len(ordered)) - 1)
    return round(float(ordered[index]), 3)


def _safe_result_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def run_load_test(
    config: LoadTestConfig,
    *,
    requester: Requester | None = None,
    clock: Callable[[], float] = perf_counter,
) -> LoadTestResult:
    """Execute bounded concurrent requests and calculate release metrics."""

    send = requester or _default_requester

    def execute_one() -> RequestSample:
        started = clock()
        try:
            status = int(send(config))
            error_type = (
                None
                if status == config.expected_status
                else f"HTTP_{status}"
            )
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            error_type = f"HTTP_{status}"
        except Exception as exc:  # The report stores only the exception class.
            status = None
            error_type = type(exc).__name__
        duration_ms = max(0.0, (clock() - started) * 1000.0)
        return RequestSample(
            status_code=status,
            duration_ms=round(duration_ms, 3),
            error_type=error_type,
        )

    samples: list[RequestSample] = []
    with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        futures = [executor.submit(execute_one) for _ in range(config.requests)]
        for future in as_completed(futures):
            samples.append(future.result())

    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    latencies = [sample.duration_ms for sample in samples]
    successful = 0

    for sample in samples:
        if sample.status_code is not None:
            key = str(sample.status_code)
            status_counts[key] = status_counts.get(key, 0) + 1
        if sample.error_type is None:
            successful += 1
        else:
            error_counts[sample.error_type] = (
                error_counts.get(sample.error_type, 0) + 1
            )

    failed = len(samples) - successful
    error_rate = round((failed / len(samples)) * 100.0, 3)
    p95 = _percentile(latencies, 95.0)
    passed = (
        len(samples) == config.requests
        and error_rate <= config.maximum_error_rate_percent
        and p95 <= config.maximum_p95_ms
    )

    return LoadTestResult(
        url=_safe_result_url(config.url),
        total_requests=len(samples),
        successful_requests=successful,
        failed_requests=failed,
        error_rate_percent=error_rate,
        p50_ms=_percentile(latencies, 50.0),
        p95_ms=p95,
        p99_ms=_percentile(latencies, 99.0),
        maximum_ms=round(max(latencies, default=0.0), 3),
        status_counts=status_counts,
        error_counts=error_counts,
        passed=passed,
    )
