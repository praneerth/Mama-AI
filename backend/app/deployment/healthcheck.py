"""Container health probe for the public readiness endpoint."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def readiness_url() -> str:
    host = os.getenv("MAMA_HEALTHCHECK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("PORT", "8000").strip() or "8000"
    return f"http://{host}:{port}/health/ready"


def check(url: str | None = None, *, timeout: float = 3.0) -> bool:
    request = urllib.request.Request(
        url or readiness_url(),
        headers={"User-Agent": "mama-ai-healthcheck/1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if int(response.status) != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return bool(payload.get("ready")) and payload.get("status") == "ready"


def main() -> int:
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
