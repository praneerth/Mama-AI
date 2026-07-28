"""Release evidence, gate evaluation, and tamper-evident JSON reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import re
import tempfile

from app.release.policy import ReleasePolicy

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/\-]{1,255}$")


def _mapping_bool(value: Mapping[str, Any], name: str) -> bool:
    raw = value.get(name, False)
    if not isinstance(raw, bool):
        raise TypeError(f"{name} must be a JSON boolean.")
    return raw


def _mapping_int(value: Mapping[str, Any], name: str, default: int = 0) -> int:
    raw = value.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{name} must be a JSON integer.")
    return raw


def _mapping_float(
    value: Mapping[str, Any],
    name: str,
    default: float,
) -> float:
    raw = value.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{name} must be a JSON number.")
    return float(raw)


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    required: bool
    actual: object
    expected: object
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "actual": self.actual,
            "expected": self.expected,
            "message": self.message,
        }


@dataclass(frozen=True)
class ReleaseEvidence:
    commit_sha: str
    branch: str
    unit_tests: int = 0
    integration_tests: int = 0
    smoke_tests: int = 0
    compile_passed: bool = False
    bandit_passed: bool = False
    dependency_scan_passed: bool = False
    secret_scan_passed: bool = False
    compose_validation_passed: bool = False
    container_build_passed: bool = False
    deployment_validation_passed: bool = False
    live_smoke_passed: bool = False
    verified_backup: bool = False
    clean_worktree: bool = False
    load_requests: int = 0
    load_error_rate_percent: float = 100.0
    load_p95_ms: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReleaseEvidence":
        commit_sha = value.get("commit_sha", "")
        branch = value.get("branch", "")
        if not isinstance(commit_sha, str) or not isinstance(branch, str):
            raise TypeError("commit_sha and branch must be JSON strings.")
        return cls(
            commit_sha=commit_sha.strip(),
            branch=branch.strip(),
            unit_tests=_mapping_int(value, "unit_tests"),
            integration_tests=_mapping_int(value, "integration_tests"),
            smoke_tests=_mapping_int(value, "smoke_tests"),
            compile_passed=_mapping_bool(value, "compile_passed"),
            bandit_passed=_mapping_bool(value, "bandit_passed"),
            dependency_scan_passed=_mapping_bool(
                value, "dependency_scan_passed"
            ),
            secret_scan_passed=_mapping_bool(value, "secret_scan_passed"),
            compose_validation_passed=_mapping_bool(
                value, "compose_validation_passed"
            ),
            container_build_passed=_mapping_bool(
                value, "container_build_passed"
            ),
            deployment_validation_passed=_mapping_bool(
                value, "deployment_validation_passed"
            ),
            live_smoke_passed=_mapping_bool(value, "live_smoke_passed"),
            verified_backup=_mapping_bool(value, "verified_backup"),
            clean_worktree=_mapping_bool(value, "clean_worktree"),
            load_requests=_mapping_int(value, "load_requests"),
            load_error_rate_percent=_mapping_float(
                value, "load_error_rate_percent", 100.0
            ),
            load_p95_ms=_mapping_float(value, "load_p95_ms", 0.0),
        )

    def __post_init__(self) -> None:
        if not _COMMIT_SHA.fullmatch(self.commit_sha):
            raise ValueError("Release evidence requires a hexadecimal commit SHA.")
        if not _BRANCH_NAME.fullmatch(self.branch):
            raise ValueError("Release evidence contains an invalid branch name.")
        for name in ("unit_tests", "integration_tests", "smoke_tests", "load_requests"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative.")
        if not 0.0 <= self.load_error_rate_percent <= 100.0:
            raise ValueError("load_error_rate_percent must be between 0 and 100.")
        if self.load_p95_ms < 0:
            raise ValueError("load_p95_ms cannot be negative.")

    def as_dict(self) -> dict[str, object]:
        return {
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "unit_tests": self.unit_tests,
            "integration_tests": self.integration_tests,
            "smoke_tests": self.smoke_tests,
            "compile_passed": self.compile_passed,
            "bandit_passed": self.bandit_passed,
            "dependency_scan_passed": self.dependency_scan_passed,
            "secret_scan_passed": self.secret_scan_passed,
            "compose_validation_passed": self.compose_validation_passed,
            "container_build_passed": self.container_build_passed,
            "deployment_validation_passed": self.deployment_validation_passed,
            "live_smoke_passed": self.live_smoke_passed,
            "verified_backup": self.verified_backup,
            "clean_worktree": self.clean_worktree,
            "load_requests": self.load_requests,
            "load_error_rate_percent": self.load_error_rate_percent,
            "load_p95_ms": self.load_p95_ms,
        }


@dataclass(frozen=True)
class ReleaseReport:
    schema_version: int
    generated_at: str
    commit_sha: str
    branch: str
    passed: bool
    policy: dict[str, object]
    gates: tuple[GateResult, ...]
    evidence_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "passed": self.passed,
            "policy": dict(self.policy),
            "gates": [gate.as_dict() for gate in self.gates],
            "evidence_sha256": self.evidence_sha256,
        }


def _gate(
    name: str,
    actual: object,
    expected: object,
    passed: bool,
    *,
    required: bool = True,
) -> GateResult:
    state = "passed" if passed else "failed"
    return GateResult(
        name=name,
        passed=passed,
        required=required,
        actual=actual,
        expected=expected,
        message=f"{name} {state}.",
    )


def _evidence_hash(evidence: ReleaseEvidence) -> str:
    canonical = json.dumps(
        evidence.as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def evaluate_release(
    evidence: ReleaseEvidence,
    policy: ReleasePolicy | None = None,
    *,
    generated_at: datetime | None = None,
) -> ReleaseReport:
    active_policy = policy or ReleasePolicy()
    gates = (
        _gate(
            "tests.unit",
            evidence.unit_tests,
            f">={active_policy.minimum_unit_tests}",
            evidence.unit_tests >= active_policy.minimum_unit_tests,
        ),
        _gate(
            "tests.integration",
            evidence.integration_tests,
            f">={active_policy.minimum_integration_tests}",
            evidence.integration_tests >= active_policy.minimum_integration_tests,
        ),
        _gate(
            "tests.smoke",
            evidence.smoke_tests,
            f">={active_policy.minimum_smoke_tests}",
            evidence.smoke_tests >= active_policy.minimum_smoke_tests,
        ),
        _gate("python.compile", evidence.compile_passed, True, evidence.compile_passed),
        _gate(
            "security.bandit",
            evidence.bandit_passed,
            True,
            evidence.bandit_passed,
            required=active_policy.require_security_scans,
        ),
        _gate(
            "security.dependencies",
            evidence.dependency_scan_passed,
            True,
            evidence.dependency_scan_passed,
            required=active_policy.require_security_scans,
        ),
        _gate(
            "security.secrets",
            evidence.secret_scan_passed,
            True,
            evidence.secret_scan_passed,
            required=active_policy.require_secret_scan,
        ),
        _gate(
            "container.compose",
            evidence.compose_validation_passed,
            True,
            evidence.compose_validation_passed,
            required=active_policy.require_container_validation,
        ),
        _gate(
            "container.build",
            evidence.container_build_passed,
            True,
            evidence.container_build_passed,
            required=active_policy.require_container_validation,
        ),
        _gate(
            "deployment.environment",
            evidence.deployment_validation_passed,
            True,
            evidence.deployment_validation_passed,
            required=active_policy.require_deployment_validation,
        ),
        _gate(
            "runtime.smoke",
            evidence.live_smoke_passed,
            True,
            evidence.live_smoke_passed,
            required=active_policy.require_live_smoke,
        ),
        _gate(
            "database.backup",
            evidence.verified_backup,
            True,
            evidence.verified_backup,
            required=active_policy.require_verified_backup,
        ),
        _gate(
            "repository.clean",
            evidence.clean_worktree,
            True,
            evidence.clean_worktree,
            required=active_policy.require_clean_worktree,
        ),
        _gate(
            "load.requests",
            evidence.load_requests,
            f">={active_policy.minimum_load_requests}",
            evidence.load_requests >= active_policy.minimum_load_requests,
            required=active_policy.require_load_test,
        ),
        _gate(
            "load.error_rate_percent",
            evidence.load_error_rate_percent,
            f"<={active_policy.maximum_load_error_rate_percent}",
            evidence.load_error_rate_percent
            <= active_policy.maximum_load_error_rate_percent,
            required=active_policy.require_load_test,
        ),
        _gate(
            "load.p95_ms",
            evidence.load_p95_ms,
            f"<={active_policy.maximum_load_p95_ms}",
            evidence.load_p95_ms <= active_policy.maximum_load_p95_ms,
            required=active_policy.require_load_test,
        ),
    )
    approved = all(gate.passed for gate in gates if gate.required)
    timestamp = generated_at or datetime.now(timezone.utc)
    return ReleaseReport(
        schema_version=1,
        generated_at=timestamp.astimezone(timezone.utc).isoformat(),
        commit_sha=evidence.commit_sha,
        branch=evidence.branch,
        passed=approved,
        policy=active_policy.as_dict(),
        gates=gates,
        evidence_sha256=_evidence_hash(evidence),
    )


def write_release_report(report: ReleaseReport, output_path: str | Path) -> Path:
    """Write a report atomically so a partial file cannot approve a release."""

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        report.as_dict(),
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def read_release_evidence(path: str | Path) -> ReleaseEvidence:
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Release evidence must be a JSON object.")
    return ReleaseEvidence.from_mapping(loaded)
