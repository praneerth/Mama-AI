"""Fail-fast production configuration validation.

The validator intentionally reports only environment-variable names and safe
configuration facts. Secret values are never included in exceptions or logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable
from urllib.parse import urlparse

from app.config import settings


_PLACEHOLDER_MARKERS = (
    "replace_with",
    "change_me",
    "changeme",
    "your_key",
    "example",
    "placeholder",
)


class DeploymentConfigurationError(RuntimeError):
    """Raised when production configuration is unsafe or incomplete."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(str(issue) for issue in issues)
        summary = "; ".join(self.issues) or "Unknown deployment configuration error."
        super().__init__(summary)


@dataclass(frozen=True)
class DeploymentValidationResult:
    """Safe validation summary that never contains secret values."""

    environment: str
    validated: bool
    strict: bool
    workers: int
    trusted_hosts: tuple[str, ...]
    cors_origins: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "validated": self.validated,
            "strict": self.strict,
            "workers": self.workers,
            "trusted_hosts": list(self.trusted_hosts),
            "cors_origins": list(self.cors_origins),
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_placeholder(value: Any) -> bool:
    normalized = _text(value).lower()
    return not normalized or any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def _secret_is_valid(value: Any, *, minimum: int = 32) -> bool:
    candidate = _text(value)
    return len(candidate) >= minimum and not _is_placeholder(candidate)


def _https_url(value: Any) -> bool:
    parsed = urlparse(_text(value))
    return parsed.scheme == "https" and bool(parsed.netloc)


def _safe_origin(origin: str, *, require_https: bool) -> bool:
    if origin == "*":
        return False
    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    if require_https and parsed.scheme != "https":
        return False
    return parsed.scheme in {"http", "https"}


def _ensure_writable_directory(path_value: Any, variable_name: str, issues: list[str]) -> None:
    try:
        path = Path(path_value).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".mama-ai-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception:
        issues.append(f"{variable_name} must point to a writable directory.")


def validate_runtime_environment(
    settings_module: ModuleType | Any = settings,
    *,
    force: bool | None = None,
) -> DeploymentValidationResult:
    """Validate deployment settings and fail closed in production.

    Strict validation runs when ``ENVIRONMENT=production``, when
    ``MAMA_DEPLOYMENT_VALIDATE_ENV=True``, or when ``force=True``.
    """

    environment = _text(getattr(settings_module, "ENVIRONMENT", "development")).lower()
    configured_validation = bool(
        getattr(settings_module, "DEPLOYMENT_VALIDATE_ENV", False)
    )
    strict = bool(force) if force is not None else (
        environment == "production" or configured_validation
    )

    workers = int(getattr(settings_module, "DEPLOYMENT_WORKERS", 1))
    trusted_hosts = tuple(
        str(item).strip()
        for item in getattr(settings_module, "TRUSTED_HOSTS", ())
        if str(item).strip()
    )
    cors_origins = tuple(
        str(item).strip()
        for item in getattr(settings_module, "CORS_ORIGINS", ())
        if str(item).strip()
    )

    if not strict:
        return DeploymentValidationResult(
            environment=environment,
            validated=False,
            strict=False,
            workers=workers,
            trusted_hosts=trusted_hosts,
            cors_origins=cors_origins,
        )

    issues: list[str] = []

    if environment != "production":
        issues.append("ENVIRONMENT must be production when strict deployment validation is enabled.")

    if bool(getattr(settings_module, "DEBUG", False)):
        issues.append("DEBUG must be False in production.")

    if workers != 1:
        issues.append(
            "MAMA_DEPLOYMENT_WORKERS must be 1 because SQLite and the in-process durable worker are single-process services."
        )

    if not bool(getattr(settings_module, "AUTH_ENABLED", False)):
        issues.append("MAMA_AUTH_ENABLED must be True in production.")

    if not bool(getattr(settings_module, "ACCOUNT_AUTH_ENABLED", False)):
        issues.append("MAMA_ACCOUNT_AUTH_ENABLED must be True in production.")

    if bool(getattr(settings_module, "AUTH_STATIC_COMPATIBILITY_ENABLED", False)):
        issues.append("MAMA_STATIC_TOKEN_COMPATIBILITY_ENABLED must be False in production.")

    if bool(getattr(settings_module, "AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED", False)):
        issues.append("MAMA_AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED must be False in production.")

    if not _secret_is_valid(getattr(settings_module, "AUTH_SIGNING_SECRET", "")):
        issues.append("MAMA_AUTH_SIGNING_SECRET must be a non-placeholder secret of at least 32 characters.")

    if bool(getattr(settings_module, "AUTH_TWO_FACTOR_ENABLED", False)) and not _secret_is_valid(
        getattr(settings_module, "AUTH_TWO_FACTOR_SECRET_KEY", "")
    ):
        issues.append(
            "MAMA_AUTH_TWO_FACTOR_SECRET_KEY must be an independent non-placeholder secret of at least 32 characters."
        )

    if bool(getattr(settings_module, "DEPLOYMENT_REQUIRE_AI_KEY", True)) and _is_placeholder(
        getattr(settings_module, "GEMINI_API_KEY", "")
    ):
        issues.append("GEMINI_API_KEY must be configured for the production AI service.")

    require_https = bool(getattr(settings_module, "DEPLOYMENT_REQUIRE_HTTPS", True))
    if require_https and not _https_url(
        getattr(settings_module, "AUTH_PUBLIC_BASE_URL", "")
    ):
        issues.append("MAMA_AUTH_PUBLIC_BASE_URL must be a valid HTTPS URL in production.")

    if not trusted_hosts or "*" in trusted_hosts:
        issues.append("MAMA_TRUSTED_HOSTS must contain explicit host names and must not contain '*'.")

    if not cors_origins:
        issues.append("MAMA_CORS_ORIGINS must contain at least one explicit frontend origin.")
    elif any(not _safe_origin(origin, require_https=require_https) for origin in cors_origins):
        issues.append(
            "MAMA_CORS_ORIGINS must contain explicit HTTP(S) origins; HTTPS is required by the current deployment policy."
        )

    if "*" in cors_origins and bool(
        getattr(settings_module, "CORS_ALLOW_CREDENTIALS", True)
    ):
        issues.append("Wildcard CORS cannot be combined with credentialed requests.")

    if not bool(getattr(settings_module, "DATABASE_MIGRATIONS_ENABLED", False)):
        issues.append("MAMA_DATABASE_MIGRATIONS_ENABLED must be True in production.")

    if not bool(getattr(settings_module, "DATABASE_BACKUP_ENABLED", False)):
        issues.append("MAMA_DATABASE_BACKUP_ENABLED must be True in production.")

    directory_settings = (
        ("DATA_DIR", "MAMA_DATA_DIR"),
        ("DATABASE_DIR", "MAMA_DATABASE_DIR"),
        ("DATABASE_BACKUP_DIR", "MAMA_DATABASE_BACKUP_DIR"),
        ("LOG_DIR", "MAMA_LOG_DIR"),
        ("CACHE_DIR", "MAMA_CACHE_DIR"),
        ("TEMP_DIR", "MAMA_TEMP_DIR"),
    )
    for attribute, variable_name in directory_settings:
        _ensure_writable_directory(
            getattr(settings_module, attribute, ""),
            variable_name,
            issues,
        )

    if issues:
        raise DeploymentConfigurationError(issues)

    return DeploymentValidationResult(
        environment=environment,
        validated=True,
        strict=True,
        workers=workers,
        trusted_hosts=trusted_hosts,
        cors_origins=cors_origins,
    )


def main() -> int:
    try:
        result = validate_runtime_environment(force=True)
    except DeploymentConfigurationError as exc:
        print("Mama AI production configuration is invalid:")
        for issue in exc.issues:
            print(f"- {issue}")
        return 1
    print("Mama AI production configuration is valid.")
    print(f"Environment: {result.environment}")
    print(f"Workers: {result.workers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
