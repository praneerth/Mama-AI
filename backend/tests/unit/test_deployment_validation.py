from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.deployment.validation import (
    DeploymentConfigurationError,
    validate_runtime_environment,
)


class TestDeploymentValidation(unittest.TestCase):
    def _settings(self, root: Path, **overrides):
        defaults = {
            "ENVIRONMENT": "production",
            "DEPLOYMENT_VALIDATE_ENV": True,
            "DEPLOYMENT_WORKERS": 1,
            "DEBUG": False,
            "AUTH_ENABLED": True,
            "ACCOUNT_AUTH_ENABLED": True,
            "AUTH_STATIC_COMPATIBILITY_ENABLED": False,
            "AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED": False,
            "AUTH_SIGNING_SECRET": "s" * 48,
            "AUTH_TWO_FACTOR_ENABLED": True,
            "AUTH_TWO_FACTOR_SECRET_KEY": "t" * 48,
            "DEPLOYMENT_REQUIRE_AI_KEY": True,
            "GEMINI_API_KEY": "g" * 40,
            "DEPLOYMENT_REQUIRE_HTTPS": True,
            "AUTH_PUBLIC_BASE_URL": "https://api.example.com",
            "TRUSTED_HOSTS": ("api.example.com",),
            "CORS_ORIGINS": ("https://app.example.com",),
            "CORS_ALLOW_CREDENTIALS": True,
            "DATABASE_MIGRATIONS_ENABLED": True,
            "DATABASE_BACKUP_ENABLED": True,
            "DATA_DIR": root / "data",
            "DATABASE_DIR": root / "database",
            "DATABASE_BACKUP_DIR": root / "backups",
            "LOG_DIR": root / "logs",
            "CACHE_DIR": root / "cache",
            "TEMP_DIR": root / "temp",
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_valid_production_environment_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = validate_runtime_environment(
                self._settings(Path(directory)),
                force=True,
            )
        self.assertTrue(result.validated)
        self.assertEqual(result.workers, 1)
        self.assertEqual(result.environment, "production")

    def test_non_strict_development_environment_is_not_rejected(self):
        settings = SimpleNamespace(
            ENVIRONMENT="development",
            DEPLOYMENT_VALIDATE_ENV=False,
            DEPLOYMENT_WORKERS=1,
            TRUSTED_HOSTS=("localhost",),
            CORS_ORIGINS=("http://localhost:5173",),
        )
        result = validate_runtime_environment(settings)
        self.assertFalse(result.validated)
        self.assertFalse(result.strict)

    def test_multiple_workers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(Path(directory), DEPLOYMENT_WORKERS=2)
            with self.assertRaises(DeploymentConfigurationError) as context:
                validate_runtime_environment(settings, force=True)
        self.assertIn("MAMA_DEPLOYMENT_WORKERS", str(context.exception))

    def test_unsafe_authentication_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(
                Path(directory),
                DEBUG=True,
                AUTH_STATIC_COMPATIBILITY_ENABLED=True,
                AUTH_SIGNING_SECRET="REPLACE_WITH_SECRET",
            )
            with self.assertRaises(DeploymentConfigurationError) as context:
                validate_runtime_environment(settings, force=True)
        message = str(context.exception)
        self.assertIn("DEBUG", message)
        self.assertIn("MAMA_STATIC_TOKEN_COMPATIBILITY_ENABLED", message)
        self.assertIn("MAMA_AUTH_SIGNING_SECRET", message)
        self.assertNotIn("REPLACE_WITH_SECRET", message)

    def test_wildcard_hosts_and_insecure_origins_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(
                Path(directory),
                TRUSTED_HOSTS=("*",),
                CORS_ORIGINS=("http://app.example.com",),
            )
            with self.assertRaises(DeploymentConfigurationError) as context:
                validate_runtime_environment(settings, force=True)
        message = str(context.exception)
        self.assertIn("MAMA_TRUSTED_HOSTS", message)
        self.assertIn("MAMA_CORS_ORIGINS", message)

    def test_missing_backup_and_migrations_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(
                Path(directory),
                DATABASE_MIGRATIONS_ENABLED=False,
                DATABASE_BACKUP_ENABLED=False,
            )
            with self.assertRaises(DeploymentConfigurationError) as context:
                validate_runtime_environment(settings, force=True)
        message = str(context.exception)
        self.assertIn("MAMA_DATABASE_MIGRATIONS_ENABLED", message)
        self.assertIn("MAMA_DATABASE_BACKUP_ENABLED", message)


if __name__ == "__main__":
    unittest.main()
