"""Release thresholds and mandatory production gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import os


def _read_bool(
    environment: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw = environment.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _read_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int = 0,
) -> int:
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def _read_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
) -> float:
    raw = environment.get(name)
    if raw is None:
        return float(default)
    try:
        value = float(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


@dataclass(frozen=True)
class ReleasePolicy:
    """Minimum evidence required before a backend release is approved."""

    minimum_unit_tests: int = 500
    minimum_integration_tests: int = 100
    minimum_smoke_tests: int = 5
    minimum_load_requests: int = 100
    maximum_load_error_rate_percent: float = 1.0
    maximum_load_p95_ms: float = 1000.0
    require_security_scans: bool = True
    require_secret_scan: bool = True
    require_container_validation: bool = True
    require_deployment_validation: bool = True
    require_verified_backup: bool = True
    require_clean_worktree: bool = True
    require_live_smoke: bool = True
    require_load_test: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "minimum_unit_tests": self.minimum_unit_tests,
            "minimum_integration_tests": self.minimum_integration_tests,
            "minimum_smoke_tests": self.minimum_smoke_tests,
            "minimum_load_requests": self.minimum_load_requests,
        }
        for name, value in integer_fields.items():
            if not isinstance(value, int):
                raise TypeError(f"{name} must be an integer.")
            if value < 0:
                raise ValueError(f"{name} cannot be negative.")

        if not 0.0 <= self.maximum_load_error_rate_percent <= 100.0:
            raise ValueError(
                "maximum_load_error_rate_percent must be between 0 and 100."
            )
        if self.maximum_load_p95_ms <= 0:
            raise ValueError("maximum_load_p95_ms must be greater than zero.")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ReleasePolicy":
        values = os.environ if environment is None else environment
        return cls(
            minimum_unit_tests=_read_int(
                values, "MAMA_RELEASE_MIN_UNIT_TESTS", 500
            ),
            minimum_integration_tests=_read_int(
                values, "MAMA_RELEASE_MIN_INTEGRATION_TESTS", 100
            ),
            minimum_smoke_tests=_read_int(
                values, "MAMA_RELEASE_MIN_SMOKE_TESTS", 5
            ),
            minimum_load_requests=_read_int(
                values, "MAMA_RELEASE_MIN_LOAD_REQUESTS", 100
            ),
            maximum_load_error_rate_percent=_read_float(
                values, "MAMA_RELEASE_MAX_LOAD_ERROR_PERCENT", 1.0
            ),
            maximum_load_p95_ms=_read_float(
                values, "MAMA_RELEASE_MAX_LOAD_P95_MS", 1000.0,
                minimum=0.001,
            ),
            require_security_scans=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_SECURITY_SCANS", True
            ),
            require_secret_scan=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_SECRET_SCAN", True
            ),
            require_container_validation=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_CONTAINER", True
            ),
            require_deployment_validation=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_DEPLOYMENT_VALIDATION", True
            ),
            require_verified_backup=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_VERIFIED_BACKUP", True
            ),
            require_clean_worktree=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_CLEAN_WORKTREE", True
            ),
            require_live_smoke=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_LIVE_SMOKE", True
            ),
            require_load_test=_read_bool(
                values, "MAMA_RELEASE_REQUIRE_LOAD_TEST", True
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "minimum_unit_tests": self.minimum_unit_tests,
            "minimum_integration_tests": self.minimum_integration_tests,
            "minimum_smoke_tests": self.minimum_smoke_tests,
            "minimum_load_requests": self.minimum_load_requests,
            "maximum_load_error_rate_percent": (
                self.maximum_load_error_rate_percent
            ),
            "maximum_load_p95_ms": self.maximum_load_p95_ms,
            "require_security_scans": self.require_security_scans,
            "require_secret_scan": self.require_secret_scan,
            "require_container_validation": self.require_container_validation,
            "require_deployment_validation": self.require_deployment_validation,
            "require_verified_backup": self.require_verified_backup,
            "require_clean_worktree": self.require_clean_worktree,
            "require_live_smoke": self.require_live_smoke,
            "require_load_test": self.require_load_test,
        }
