from __future__ import annotations

import unittest
from pathlib import Path


class TestDeploymentArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = Path(__file__).resolve().parents[2]
        cls.repository = cls.backend.parent

    def test_dockerfile_runs_as_non_root_user(self):
        content = (self.backend / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER mama-ai", content)
        self.assertIn("HEALTHCHECK", content)
        self.assertIn('CMD ["python", "-m", "app.deployment.launcher"]', content)

    def test_production_compose_has_single_worker_and_security_controls(self):
        content = (self.repository / "compose.backend.yaml").read_text(encoding="utf-8")
        self.assertIn('MAMA_DEPLOYMENT_WORKERS: "1"', content)
        self.assertIn("read_only: true", content)
        self.assertIn("no-new-privileges:true", content)
        self.assertIn("cap_drop:", content)
        self.assertNotIn("MAMA_AUTH_SIGNING_SECRET:", content)

    def test_ci_workflow_contains_required_gates(self):
        content = (
            self.repository / ".github" / "workflows" / "backend-ci.yml"
        ).read_text(encoding="utf-8")
        for expected in (
            "Run unit tests",
            "Run integration tests",
            "Static security scan",
            "Dependency vulnerability scan",
            "Build backend image",
            "gitleaks/gitleaks-action",
        ):
            self.assertIn(expected, content)

    def test_dockerignore_excludes_runtime_secrets_and_data(self):
        content = (self.backend / ".dockerignore").read_text(encoding="utf-8")
        for expected in (".env", "*.db", "*.log", "venv"):
            self.assertIn(expected, content)


if __name__ == "__main__":
    unittest.main()
