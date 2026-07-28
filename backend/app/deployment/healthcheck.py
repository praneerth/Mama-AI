"""Container health probe for the public readiness endpoint."""

from __future__ import annotations

from http.client import HTTPConnection, HTTPSConnection
import json
import os
import sys
from urllib.parse import SplitResult, urlsplit, urlunsplit


def readiness_url() -> str:
    host = os.getenv("MAMA_HEALTHCHECK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("PORT", "8000").strip() or "8000"
    return f"http://{host}:{port}/health/ready"


def _validated_url(value: str) -> SplitResult:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Healthcheck URL must use http or https.")
    if not parsed.hostname:
        raise ValueError("Healthcheck URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Healthcheck URL must not include credentials.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Healthcheck URL contains an invalid port.") from exc
    return parsed


def _perform_get(url: str, timeout: float) -> tuple[int, bytes]:
    parsed = _validated_url(url)
    connection_type = (
        HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    )
    connection = connection_type(
        parsed.hostname,
        parsed.port,
        timeout=timeout,
    )
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request(
            "GET",
            target,
            headers={"User-Agent": "mama-ai-healthcheck/1"},
        )
        response = connection.getresponse()
        return int(response.status), response.read()
    finally:
        connection.close()


def check(url: str | None = None, *, timeout: float = 3.0) -> bool:
    if timeout <= 0:
        return False
    try:
        status, body = _perform_get(url or readiness_url(), timeout)
        if status != 200:
            return False
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return bool(payload.get("ready")) and payload.get("status") == "ready"


def main() -> int:
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
