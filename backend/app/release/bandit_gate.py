"""Reviewed Bandit gate for Mama AI's SQLite query construction.

Bandit's B608 check cannot distinguish untrusted SQL interpolation from Mama
AI's immutable table identifiers and fixed optional clauses. This gate keeps
Bandit enabled, rejects every unreviewed finding, and permits only exact
fingerprints from the committed review baseline.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


_REVIEWED_TEST_ID = "B608"
_SCHEMA_VERSION = 1
_LINE_NUMBER_PREFIX = re.compile(r"^\d+\s")
_DEFAULT_TARGETS = (
    "app/api",
    "app/core",
    "app/database",
    "app/deployment",
    "app/middleware",
    "app/observability",
    "app/release",
)


@dataclass(frozen=True)
class BanditGateResult:
    passed: bool
    reviewed_findings: int
    unreviewed_findings: tuple[str, ...]
    stale_allowlist_entries: tuple[str, ...]
    errors: tuple[str, ...]

    def summary(self) -> str:
        if self.passed:
            return (
                "Bandit review gate passed: "
                f"{self.reviewed_findings} reviewed {_REVIEWED_TEST_ID} "
                "findings and 0 unreviewed findings."
            )
        parts = ["Bandit review gate failed."]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        if self.unreviewed_findings:
            parts.append(
                f"unreviewed_findings={len(self.unreviewed_findings)}"
            )
        if self.stale_allowlist_entries:
            parts.append(
                "stale_allowlist_entries="
                f"{len(self.stale_allowlist_entries)}"
            )
        return " ".join(parts)


def _normalise_filename(value: str) -> str:
    normalised = str(value).replace("\\", "/").strip()
    while normalised.startswith("./"):
        normalised = normalised[2:]
    if "/backend/" in normalised:
        normalised = normalised.split("/backend/", 1)[1]
    elif normalised.startswith("backend/"):
        normalised = normalised[len("backend/") :]
    return normalised


def _normalise_code(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    normalised = [_LINE_NUMBER_PREFIX.sub("", line, count=1) for line in lines]
    return "\n".join(normalised).rstrip() + "\n"


def finding_fingerprint(finding: Mapping[str, Any]) -> str:
    payload = {
        "filename": _normalise_filename(str(finding.get("filename", ""))),
        "test_id": str(finding.get("test_id", "")),
        "code": _normalise_code(str(finding.get("code", ""))),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _finding_key(finding: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _normalise_filename(str(finding.get("filename", ""))),
        finding_fingerprint(finding),
    )


def _format_key(key: tuple[str, str], count: int) -> str:
    filename, fingerprint = key
    return f"{filename}:{fingerprint[:16]} count={count}"


def validate_report(
    report: Mapping[str, Any],
    allowlist: Mapping[str, Any],
) -> BanditGateResult:
    errors: list[str] = []

    if allowlist.get("schema_version") != _SCHEMA_VERSION:
        errors.append("Unsupported Bandit allowlist schema version.")

    report_errors = report.get("errors", [])
    if not isinstance(report_errors, list):
        errors.append("Bandit report errors field is invalid.")
    elif report_errors:
        errors.extend(f"Bandit error: {item}" for item in report_errors)

    findings = report.get("results", [])
    if not isinstance(findings, list):
        findings = []
        errors.append("Bandit report results field is invalid.")

    expected_entries = allowlist.get("findings", [])
    if not isinstance(expected_entries, list):
        expected_entries = []
        errors.append("Bandit allowlist findings field is invalid.")

    expected: Counter[tuple[str, str]] = Counter()
    for entry in expected_entries:
        if not isinstance(entry, Mapping):
            errors.append("Bandit allowlist contains an invalid entry.")
            continue
        filename = _normalise_filename(str(entry.get("filename", "")))
        fingerprint = str(entry.get("fingerprint", "")).strip().lower()
        count = entry.get("count", 1)
        if (
            not filename
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
            or not isinstance(count, int)
            or count < 1
        ):
            errors.append("Bandit allowlist contains a malformed entry.")
            continue
        expected[(filename, fingerprint)] += count

    actual: Counter[tuple[str, str]] = Counter()
    unreviewed: list[str] = []

    for finding in findings:
        if not isinstance(finding, Mapping):
            unreviewed.append("invalid finding object")
            continue
        test_id = str(finding.get("test_id", ""))
        filename = _normalise_filename(str(finding.get("filename", "")))
        line_number = finding.get("line_number", "?")
        if test_id != _REVIEWED_TEST_ID:
            unreviewed.append(f"{test_id} {filename}:{line_number}")
            continue
        actual[_finding_key(finding)] += 1

    unexpected = actual - expected
    stale = expected - actual

    for key, count in sorted(unexpected.items()):
        unreviewed.append(_format_key(key, count))
    stale_entries = tuple(
        _format_key(key, count) for key, count in sorted(stale.items())
    )

    return BanditGateResult(
        passed=not errors and not unreviewed and not stale_entries,
        reviewed_findings=sum(actual.values()) if actual == expected else 0,
        unreviewed_findings=tuple(unreviewed),
        stale_allowlist_entries=stale_entries,
        errors=tuple(errors),
    )


def load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def _bandit_diagnostic(completed: subprocess.CompletedProcess[str]) -> str:
    parts = [
        value.strip()
        for value in (completed.stdout, completed.stderr)
        if value and value.strip()
    ]
    return "\n".join(parts)


def run_bandit(
    backend_root: Path,
    *,
    targets: Sequence[str] = _DEFAULT_TARGETS,
) -> tuple[Mapping[str, Any], str]:
    # Bandit can emit logging or progress text on stdout on some Windows
    # installations. Writing JSON to a dedicated file prevents that text from
    # corrupting the report consumed by this release gate.
    with tempfile.TemporaryDirectory(prefix="mama-ai-bandit-") as temp_dir:
        report_path = Path(temp_dir) / "bandit-report.json"
        command = (
            sys.executable,
            "-m",
            "bandit",
            "-q",
            "-r",
            *targets,
            "-ll",
            "-ii",
            "-f",
            "json",
            "-o",
            str(report_path),
        )
        completed = subprocess.run(
            command,
            cwd=str(backend_root),
            capture_output=True,
            text=True,
            check=False,
        )
        diagnostic = _bandit_diagnostic(completed)

        if not report_path.is_file():
            raise RuntimeError(
                "Bandit did not create its JSON report. "
                + (diagnostic or "No diagnostic was returned.")
            )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            detail = f" Details: {diagnostic}" if diagnostic else ""
            raise RuntimeError(
                "Bandit created an invalid JSON report." + detail
            ) from exc

    if not isinstance(report, Mapping):
        raise RuntimeError("Bandit returned an invalid report object.")
    return report, diagnostic


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Bandit and enforce the reviewed B608 baseline."
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Validate an existing Bandit JSON report instead of running Bandit.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        help="Override the committed Bandit review allowlist.",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        help="Write the generated Bandit report to this path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    backend_root = Path(__file__).resolve().parents[2]
    allowlist_path = (
        args.allowlist
        or backend_root / "release" / "bandit_b608_allowlist.json"
    )

    try:
        allowlist = load_json(allowlist_path)
        if args.report:
            report = load_json(args.report.resolve())
            diagnostic = ""
        else:
            report, diagnostic = run_bandit(backend_root)
            if args.write_report:
                args.write_report.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Bandit review gate failed: {exc}", file=sys.stderr)
        return 2

    result = validate_report(report, allowlist)
    print(result.summary())

    if diagnostic.strip():
        print(diagnostic.strip(), file=sys.stderr)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    for finding in result.unreviewed_findings:
        print(f"UNREVIEWED: {finding}", file=sys.stderr)
    for entry in result.stale_allowlist_entries:
        print(f"STALE: {entry}", file=sys.stderr)

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
