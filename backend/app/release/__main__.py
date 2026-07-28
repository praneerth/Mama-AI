"""CLI for load testing and evaluating release evidence."""

from __future__ import annotations

import argparse
import json
import sys

from app.release.load import LoadTestConfig, run_load_test
from app.release.policy import ReleasePolicy
from app.release.report import (
    evaluate_release,
    read_release_evidence,
    write_release_report,
)


def _load_command(args: argparse.Namespace) -> int:
    headers: dict[str, str] = {}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"
    result = run_load_test(
        LoadTestConfig(
            url=args.url,
            requests=args.requests,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout,
            expected_status=args.expected_status,
            maximum_error_rate_percent=args.max_error_rate,
            maximum_p95_ms=args.max_p95_ms,
            method=args.method,
            headers=headers,
        )
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0 if result.passed else 1


def _evaluate_command(args: argparse.Namespace) -> int:
    evidence = read_release_evidence(args.evidence)
    report = evaluate_release(evidence, ReleasePolicy.from_environment())
    write_release_report(report, args.output)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.release")
    subparsers = parser.add_subparsers(dest="command", required=True)

    load = subparsers.add_parser("load", help="Run bounded HTTP load validation.")
    load.add_argument("--url", required=True)
    load.add_argument("--requests", type=int, default=100)
    load.add_argument("--concurrency", type=int, default=10)
    load.add_argument("--timeout", type=float, default=5.0)
    load.add_argument("--expected-status", type=int, default=200)
    load.add_argument("--max-error-rate", type=float, default=1.0)
    load.add_argument("--max-p95-ms", type=float, default=1000.0)
    load.add_argument("--method", default="GET")
    load.add_argument("--bearer-token", default="")
    load.set_defaults(handler=_load_command)

    evaluate = subparsers.add_parser(
        "evaluate", help="Evaluate JSON release evidence."
    )
    evaluate.add_argument("--evidence", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.set_defaults(handler=_evaluate_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (OSError, TypeError, ValueError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
