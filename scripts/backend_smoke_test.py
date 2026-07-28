"""Post-deployment smoke check with no third-party dependencies."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch_json(url: str, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "mama-ai-deployment-smoke/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    checks = (
        ("liveness", f"{base}/health", lambda body: body.get("status") == "healthy"),
        (
            "readiness",
            f"{base}/health/ready",
            lambda body: body.get("status") == "ready" and body.get("ready") is True,
        ),
    )
    try:
        for name, url, predicate in checks:
            status, body = fetch_json(url, args.timeout)
            if status != 200 or not predicate(body):
                print(f"{name} failed: status={status}", file=sys.stderr)
                return 1
            print(f"{name}: OK")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"smoke test failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
