import json
import unittest
from pathlib import Path


class TestReleaseArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_root = Path(__file__).resolve().parents[3]

    def read(self, relative: str) -> str:
        return (self.repository_root / relative).read_text(encoding="utf-8")

    def test_release_workflow_contains_required_gates(self) -> None:
        workflow = self.read(".github/workflows/backend-release.yml")
        for required in (
            "Unit tests",
            "Integration tests",
            "Smoke tests",
            "Bandit",
            "Dependency audit",
            "gitleaks/gitleaks-action",
            "docker build",
        ):
            self.assertIn(required, workflow)

    def test_release_document_warns_about_capacity_claims(self) -> None:
        document = self.read("backend/docs/release_testing.md")
        self.assertIn("does not claim", document)
        self.assertIn("representative staging environment", document)
        self.assertIn("verified database backup", document)

    def test_example_evidence_is_valid_json_and_contains_no_secret(self) -> None:
        evidence = json.loads(
            self.read("backend/release/evidence.example.json")
        )
        self.assertEqual(evidence["unit_tests"], 532)
        encoded = json.dumps(evidence).lower()
        self.assertNotIn("bearer", encoded)
        self.assertNotIn("password", encoded)
        self.assertNotIn("api_key", encoded)

    def test_local_release_outputs_are_ignored(self) -> None:
        ignore = self.read(".gitignore")
        self.assertIn("backend/release/*.local.json", ignore)
        self.assertIn("!backend/release/evidence.example.json", ignore)



    def test_bandit_review_gate_and_allowlist_are_committed(self) -> None:
        workflow = self.read(".github/workflows/backend-release.yml")
        self.assertIn("python -m app.release.bandit_gate", workflow)

        allowlist = json.loads(
            self.read("backend/release/bandit_b608_allowlist.json")
        )
        self.assertEqual(allowlist["schema_version"], 1)
        self.assertEqual(allowlist["reviewed_finding_count"], 190)
        self.assertEqual(
            sum(entry.get("count", 1) for entry in allowlist["findings"]),
            190,
        )

    def test_load_script_uses_environment_for_optional_token(self) -> None:
        script = self.read("scripts/backend_load_test.py")
        self.assertIn("MAMA_RELEASE_BEARER_TOKEN", script)
        self.assertNotIn("Bearer secret", script)
