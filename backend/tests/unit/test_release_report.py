import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.release.policy import ReleasePolicy
from app.release.report import (
    ReleaseEvidence,
    evaluate_release,
    read_release_evidence,
    write_release_report,
)


class TestReleaseReport(unittest.TestCase):
    def passing_evidence(self) -> ReleaseEvidence:
        return ReleaseEvidence(
            commit_sha="a" * 40,
            branch="develop",
            unit_tests=504,
            integration_tests=118,
            smoke_tests=5,
            compile_passed=True,
            bandit_passed=True,
            dependency_scan_passed=True,
            secret_scan_passed=True,
            compose_validation_passed=True,
            container_build_passed=True,
            deployment_validation_passed=True,
            live_smoke_passed=True,
            verified_backup=True,
            clean_worktree=True,
            load_requests=100,
            load_error_rate_percent=0.0,
            load_p95_ms=250.0,
        )

    def test_complete_evidence_approves_release(self) -> None:
        report = evaluate_release(
            self.passing_evidence(),
            generated_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
        )
        self.assertTrue(report.passed)
        self.assertTrue(all(gate.passed for gate in report.gates))
        self.assertEqual(len(report.evidence_sha256), 64)
        self.assertEqual(report.generated_at, "2026-07-28T00:00:00+00:00")

    def test_single_required_failure_blocks_release(self) -> None:
        values = self.passing_evidence().as_dict()
        values["verified_backup"] = False
        report = evaluate_release(ReleaseEvidence.from_mapping(values))
        self.assertFalse(report.passed)
        failed = [gate.name for gate in report.gates if gate.required and not gate.passed]
        self.assertEqual(failed, ["database.backup"])

    def test_optional_gate_does_not_block_preflight(self) -> None:
        values = self.passing_evidence().as_dict()
        values["verified_backup"] = False
        policy = ReleasePolicy(require_verified_backup=False)
        report = evaluate_release(ReleaseEvidence.from_mapping(values), policy)
        self.assertTrue(report.passed)
        backup_gate = next(g for g in report.gates if g.name == "database.backup")
        self.assertFalse(backup_gate.required)
        self.assertFalse(backup_gate.passed)

    def test_atomic_report_round_trip(self) -> None:
        report = evaluate_release(self.passing_evidence())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release-report.json"
            written = write_release_report(report, path)
            self.assertEqual(written, path.resolve())
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(loaded["passed"])
        self.assertEqual(loaded["commit_sha"], "a" * 40)
        self.assertEqual(len(loaded["gates"]), 16)

    def test_evidence_reader_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_release_evidence(path)

    def test_string_boolean_cannot_approve_gate(self) -> None:
        values = self.passing_evidence().as_dict()
        values["verified_backup"] = "false"
        with self.assertRaises(TypeError):
            ReleaseEvidence.from_mapping(values)

    def test_invalid_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReleaseEvidence(commit_sha="", branch="develop")
        with self.assertRaises(ValueError):
            ReleaseEvidence(commit_sha="a", branch="", load_p95_ms=1)
        with self.assertRaises(ValueError):
            ReleaseEvidence(
                commit_sha="a",
                branch="develop",
                load_error_rate_percent=101,
            )
