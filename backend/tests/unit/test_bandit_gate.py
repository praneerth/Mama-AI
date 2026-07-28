from __future__ import annotations

import copy
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from app.release.bandit_gate import (
    finding_fingerprint,
    run_bandit,
    validate_report,
)


def finding(
    *,
    test_id: str = "B608",
    filename: str = r"app\database\state_db.py",
    code: str = (
        "10 connection.execute(\n"
        "11     f\"SELECT * FROM {TASK_TABLE} WHERE task_id = ?\"\n"
        "12 )\n"
    ),
    line_number: int = 11,
) -> dict[str, object]:
    return {
        "test_id": test_id,
        "filename": filename,
        "code": code,
        "line_number": line_number,
    }


def allowlist_for(*findings: dict[str, object]) -> dict[str, object]:
    entries: dict[tuple[str, str], int] = {}
    for item in findings:
        filename = str(item["filename"]).replace("\\", "/")
        key = (filename, finding_fingerprint(item))
        entries[key] = entries.get(key, 0) + 1
    return {
        "schema_version": 1,
        "findings": [
            {
                "filename": filename,
                "fingerprint": fingerprint,
                "count": count,
            }
            for (filename, fingerprint), count in sorted(entries.items())
        ],
    }


class TestBanditGate(unittest.TestCase):
    def test_exact_reviewed_findings_pass(self) -> None:
        item = finding()
        result = validate_report(
            {"errors": [], "results": [item]},
            allowlist_for(item),
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.reviewed_findings, 1)

    def test_line_number_changes_do_not_invalidate_review(self) -> None:
        reviewed = finding()
        shifted = finding(
            code=(
                "110 connection.execute(\n"
                "111     f\"SELECT * FROM {TASK_TABLE} WHERE task_id = ?\"\n"
                "112 )\n"
            ),
            line_number=111,
        )
        result = validate_report(
            {"errors": [], "results": [shifted]},
            allowlist_for(reviewed),
        )
        self.assertTrue(result.passed)

    def test_code_change_is_unreviewed_and_old_entry_is_stale(self) -> None:
        reviewed = finding()
        changed = finding(
            code=(
                "10 connection.execute(\n"
                "11     f\"SELECT * FROM {user_input}\"\n"
                "12 )\n"
            )
        )
        result = validate_report(
            {"errors": [], "results": [changed]},
            allowlist_for(reviewed),
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.unreviewed_findings), 1)
        self.assertEqual(len(result.stale_allowlist_entries), 1)

    def test_non_b608_finding_is_rejected(self) -> None:
        item = finding(test_id="B310")
        result = validate_report(
            {"errors": [], "results": [item]},
            {"schema_version": 1, "findings": []},
        )
        self.assertFalse(result.passed)
        self.assertIn("B310", result.unreviewed_findings[0])

    def test_duplicate_review_count_is_enforced(self) -> None:
        item = finding()
        allowlist = allowlist_for(item, item)
        result = validate_report(
            {"errors": [], "results": [copy.deepcopy(item)]},
            allowlist,
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.stale_allowlist_entries), 1)

    def test_bandit_report_errors_fail_gate(self) -> None:
        result = validate_report(
            {"errors": ["could not scan file"], "results": []},
            {"schema_version": 1, "findings": []},
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.errors), 1)

    def test_invalid_schema_fails_gate(self) -> None:
        result = validate_report(
            {"errors": [], "results": []},
            {"schema_version": 99, "findings": []},
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.errors), 1)

    def test_run_bandit_reads_dedicated_json_file(self) -> None:
        expected_report = {"errors": [], "results": []}
        captured_command: list[str] = []

        def fake_run(command: tuple[str, ...], **_: object) -> CompletedProcess[str]:
            captured_command.extend(command)
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_text(
                json.dumps(expected_report),
                encoding="utf-8-sig",
            )
            return CompletedProcess(
                command,
                1,
                stdout="Bandit progress text that is not JSON",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.release.bandit_gate.subprocess.run",
                side_effect=fake_run,
            ):
                report, diagnostic = run_bandit(
                    Path(temp_dir),
                    targets=("app/database",),
                )

        self.assertEqual(report, expected_report)
        self.assertIn("Bandit progress text", diagnostic)
        self.assertIn("-q", captured_command)
        self.assertIn("-o", captured_command)

    def test_run_bandit_fails_when_report_file_is_missing(self) -> None:
        completed = CompletedProcess(
            ("bandit",),
            2,
            stdout="",
            stderr="Bandit failed before writing the report",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.release.bandit_gate.subprocess.run",
                return_value=completed,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "did not create its JSON report",
                ):
                    run_bandit(
                        Path(temp_dir),
                        targets=("app/database",),
                    )


if __name__ == "__main__":
    unittest.main()
