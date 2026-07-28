"""
Mama AI Configuration
Production Settings
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# =====================================================
# Project Root and Environment
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[2]

# Local secrets stay in backend/.env and must never be committed.
load_dotenv(
    BASE_DIR / ".env",
    override=False,
)


def _environment_bool(
    name: str,
    default: bool,
) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise ValueError(
        f"{name} must be a boolean value."
    )


def _environment_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(
            raw_value.strip()
        )

    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be an integer."
        ) from exc

    if value < minimum:
        raise ValueError(
            f"{name} must be at least {minimum}."
        )

    return value


def _environment_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
) -> float:
    raw_value = os.getenv(name)

    if raw_value is None:
        return float(default)

    try:
        value = float(raw_value.strip())

    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be a number."
        ) from exc

    if value < minimum:
        raise ValueError(
            f"{name} must be at least {minimum}."
        )

    return value


def _environment_csv(
    name: str,
    default: str,
) -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    values = tuple(
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    )
    return values


def _environment_path(
    name: str,
    default: Path,
) -> Path:
    raw_value = os.getenv(name)
    candidate = Path(raw_value).expanduser() if raw_value else default
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate.resolve()


# =====================================================
# Application
# =====================================================

APP_NAME = os.getenv(
    "APP_NAME",
    "Mama AI",
).strip() or "Mama AI"

APP_VERSION = os.getenv(
    "APP_VERSION",
    "1.0.0",
).strip() or "1.0.0"

ENVIRONMENT = (
    os.getenv(
        "ENVIRONMENT",
        "development",
    ).strip().lower()
    or "development"
)

DEBUG = _environment_bool(
    "DEBUG",
    True,
)

HOST = os.getenv(
    "HOST",
    "127.0.0.1",
).strip() or "127.0.0.1"

PORT = _environment_int(
    "PORT",
    8000,
    minimum=1,
)

DEPLOYMENT_VALIDATE_ENV = _environment_bool(
    "MAMA_DEPLOYMENT_VALIDATE_ENV",
    False,
)

DEPLOYMENT_WORKERS = _environment_int(
    "MAMA_DEPLOYMENT_WORKERS",
    1,
    minimum=1,
)

DEPLOYMENT_ENABLE_DOCS = _environment_bool(
    "MAMA_DEPLOYMENT_ENABLE_DOCS",
    ENVIRONMENT != "production",
)

DEPLOYMENT_REQUIRE_HTTPS = _environment_bool(
    "MAMA_DEPLOYMENT_REQUIRE_HTTPS",
    ENVIRONMENT == "production",
)

DEPLOYMENT_REQUIRE_AI_KEY = _environment_bool(
    "MAMA_DEPLOYMENT_REQUIRE_AI_KEY",
    True,
)

CONTAINER_MODE = _environment_bool(
    "MAMA_CONTAINER_MODE",
    False,
)

CORS_ORIGINS = _environment_csv(
    "MAMA_CORS_ORIGINS",
    "http://localhost:5173",
)

CORS_ALLOW_CREDENTIALS = _environment_bool(
    "MAMA_CORS_ALLOW_CREDENTIALS",
    True,
)

TRUSTED_HOSTS = _environment_csv(
    "MAMA_TRUSTED_HOSTS",
    "localhost,127.0.0.1,testserver",
)

FORWARDED_ALLOW_IPS = os.getenv(
    "MAMA_FORWARDED_ALLOW_IPS",
    "127.0.0.1",
).strip() or "127.0.0.1"

SERVER_TIMEOUT_KEEP_ALIVE = _environment_int(
    "MAMA_SERVER_TIMEOUT_KEEP_ALIVE",
    5,
    minimum=1,
)

SERVER_GRACEFUL_SHUTDOWN_SECONDS = _environment_int(
    "MAMA_SERVER_GRACEFUL_SHUTDOWN_SECONDS",
    30,
    minimum=1,
)


# =====================================================
# Authentication
# =====================================================

AUTH_ENABLED = _environment_bool(
    "MAMA_AUTH_ENABLED",
    True,
)

AUTH_OWNER_ID = os.getenv(
    "MAMA_OWNER_ID",
    "local-user",
).strip() or "local-user"

# This value must never be logged or returned by an endpoint.
AUTH_TOKEN = os.getenv(
    "MAMA_API_TOKEN",
    "",
).strip()

AUTH_MINIMUM_TOKEN_LENGTH = 32

# Static compatibility and deliberately disabled development authentication
# retain administrative recovery access. Account-token permissions are always
# loaded from SQLite on every request instead of trusted from token claims.
AUTH_STATIC_COMPATIBILITY_ROLES = os.getenv(
    "MAMA_AUTH_STATIC_COMPATIBILITY_ROLES",
    "admin,auditor,user",
).strip() or "admin,auditor,user"


ACCOUNT_AUTH_ENABLED = _environment_bool(
    "MAMA_ACCOUNT_AUTH_ENABLED",
    True,
)

AUTH_STATIC_COMPATIBILITY_ENABLED = _environment_bool(
    "MAMA_STATIC_TOKEN_COMPATIBILITY_ENABLED",
    True,
)

# This secret signs short-lived account access tokens. It must be
# independent from MAMA_API_TOKEN and must never be logged.
AUTH_SIGNING_SECRET = os.getenv(
    "MAMA_AUTH_SIGNING_SECRET",
    "",
).strip()

AUTH_ACCESS_TOKEN_SECONDS = _environment_int(
    "MAMA_AUTH_ACCESS_TOKEN_SECONDS",
    900,
)

AUTH_REFRESH_TOKEN_SECONDS = _environment_int(
    "MAMA_AUTH_REFRESH_TOKEN_SECONDS",
    2592000,
)

AUTH_EMAIL_VERIFICATION_TOKEN_SECONDS = _environment_int(
    "MAMA_AUTH_EMAIL_VERIFICATION_TOKEN_SECONDS",
    86400,
    minimum=60,
)

AUTH_PASSWORD_RESET_TOKEN_SECONDS = _environment_int(
    "MAMA_AUTH_PASSWORD_RESET_TOKEN_SECONDS",
    1800,
    minimum=60,
)

AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED = _environment_bool(
    "MAMA_AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED",
    False,
)

AUTH_PUBLIC_BASE_URL = os.getenv(
    "MAMA_AUTH_PUBLIC_BASE_URL",
    "http://127.0.0.1:8000",
).strip().rstrip("/")

AUTH_SMTP_HOST = os.getenv(
    "MAMA_AUTH_SMTP_HOST",
    "",
).strip()

AUTH_SMTP_PORT = _environment_int(
    "MAMA_AUTH_SMTP_PORT",
    587,
)

AUTH_SMTP_USERNAME = os.getenv(
    "MAMA_AUTH_SMTP_USERNAME",
    "",
).strip()

AUTH_SMTP_PASSWORD = os.getenv(
    "MAMA_AUTH_SMTP_PASSWORD",
    "",
)

AUTH_SMTP_FROM_EMAIL = os.getenv(
    "MAMA_AUTH_SMTP_FROM_EMAIL",
    "",
).strip()

AUTH_SMTP_USE_TLS = _environment_bool(
    "MAMA_AUTH_SMTP_USE_TLS",
    True,
)

AUTH_SMTP_TIMEOUT_SECONDS = _environment_int(
    "MAMA_AUTH_SMTP_TIMEOUT_SECONDS",
    20,
)


# =====================================================
# Account Login Protection
# =====================================================

AUTH_ACCOUNT_LOCKOUT_ENABLED = _environment_bool(
    "MAMA_AUTH_ACCOUNT_LOCKOUT_ENABLED",
    True,
)

AUTH_ACCOUNT_FAILURE_LIMIT = _environment_int(
    "MAMA_AUTH_ACCOUNT_FAILURE_LIMIT",
    5,
    minimum=2,
)

AUTH_ACCOUNT_FAILURE_WINDOW_SECONDS = _environment_int(
    "MAMA_AUTH_ACCOUNT_FAILURE_WINDOW_SECONDS",
    900,
    minimum=60,
)

AUTH_ACCOUNT_LOCKOUT_SECONDS = _environment_int(
    "MAMA_AUTH_ACCOUNT_LOCKOUT_SECONDS",
    900,
    minimum=60,
)


# =====================================================
# Two-Factor Authentication
# =====================================================

AUTH_TWO_FACTOR_ENABLED = _environment_bool(
    "MAMA_AUTH_TWO_FACTOR_ENABLED",
    True,
)

# Independent server key used to derive per-user TOTP secrets.
# It must never be logged, returned by an endpoint, or committed.
AUTH_TWO_FACTOR_SECRET_KEY = os.getenv(
    "MAMA_AUTH_TWO_FACTOR_SECRET_KEY",
    "",
).strip()

AUTH_TWO_FACTOR_ISSUER = os.getenv(
    "MAMA_AUTH_TWO_FACTOR_ISSUER",
    "Mama AI",
).strip() or "Mama AI"

AUTH_TWO_FACTOR_CHALLENGE_SECONDS = _environment_int(
    "MAMA_AUTH_TWO_FACTOR_CHALLENGE_SECONDS",
    300,
    minimum=60,
)

AUTH_TWO_FACTOR_TOTP_WINDOW = _environment_int(
    "MAMA_AUTH_TWO_FACTOR_TOTP_WINDOW",
    1,
    minimum=0,
)

AUTH_TWO_FACTOR_RECOVERY_CODE_COUNT = _environment_int(
    "MAMA_AUTH_TWO_FACTOR_RECOVERY_CODE_COUNT",
    10,
    minimum=5,
)

# =====================================================
# Trusted Devices and Account API Keys
# =====================================================

AUTH_TRUSTED_DEVICES_ENABLED = _environment_bool(
    "MAMA_AUTH_TRUSTED_DEVICES_ENABLED",
    True,
)

AUTH_API_KEYS_ENABLED = _environment_bool(
    "MAMA_AUTH_API_KEYS_ENABLED",
    True,
)

AUTH_API_KEY_MAX_ACTIVE = _environment_int(
    "MAMA_AUTH_API_KEY_MAX_ACTIVE",
    10,
    minimum=1,
)

AUTH_API_KEY_DEFAULT_EXPIRY_DAYS = _environment_int(
    "MAMA_AUTH_API_KEY_DEFAULT_EXPIRY_DAYS",
    90,
    minimum=1,
)

AUTH_API_KEY_MAX_EXPIRY_DAYS = _environment_int(
    "MAMA_AUTH_API_KEY_MAX_EXPIRY_DAYS",
    365,
    minimum=1,
)

# =====================================================
# Rate Limiting and Authentication-Abuse Protection
# =====================================================

RATE_LIMIT_ENABLED = _environment_bool(
    "MAMA_RATE_LIMIT_ENABLED",
    True,
)

RATE_LIMIT_WINDOW_SECONDS = _environment_int(
    "MAMA_RATE_LIMIT_WINDOW_SECONDS",
    60,
)

RATE_LIMIT_GENERAL_REQUESTS = _environment_int(
    "MAMA_RATE_LIMIT_GENERAL_REQUESTS",
    120,
)

RATE_LIMIT_CHAT_REQUESTS = _environment_int(
    "MAMA_RATE_LIMIT_CHAT_REQUESTS",
    30,
)

RATE_LIMIT_MEMORY_WRITE_REQUESTS = _environment_int(
    "MAMA_RATE_LIMIT_MEMORY_WRITE_REQUESTS",
    20,
)

RATE_LIMIT_ACTION_REQUESTS = _environment_int(
    "MAMA_RATE_LIMIT_ACTION_REQUESTS",
    20,
)

AUTH_FAILURE_LIMIT = _environment_int(
    "MAMA_AUTH_FAILURE_LIMIT",
    5,
)

AUTH_FAILURE_WINDOW_SECONDS = _environment_int(
    "MAMA_AUTH_FAILURE_WINDOW_SECONDS",
    60,
)

AUTH_COOLDOWN_SECONDS = _environment_int(
    "MAMA_AUTH_COOLDOWN_SECONDS",
    300,
)


# =====================================================
# Idempotency Maintenance
# =====================================================

IDEMPOTENCY_MAINTENANCE_ENABLED = _environment_bool(
    "MAMA_IDEMPOTENCY_MAINTENANCE_ENABLED",
    True,
)

IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS = _environment_int(
    "MAMA_IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS",
    300,
)

IDEMPOTENCY_CLEANUP_BATCH_SIZE = _environment_int(
    "MAMA_IDEMPOTENCY_CLEANUP_BATCH_SIZE",
    1000,
)

IDEMPOTENCY_STUCK_SECONDS = _environment_int(
    "MAMA_IDEMPOTENCY_STUCK_SECONDS",
    300,
)


# =====================================================
# Production Observability
# =====================================================

OBSERVABILITY_ENABLED = _environment_bool(
    "MAMA_OBSERVABILITY_ENABLED",
    True,
)

METRICS_ENABLED = _environment_bool(
    "MAMA_METRICS_ENABLED",
    True,
)

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO",
).strip().upper() or "INFO"

LOG_FORMAT = os.getenv(
    "MAMA_LOG_FORMAT",
    "json",
).strip().lower() or "json"

if LOG_FORMAT not in {"json", "text"}:
    raise ValueError(
        "MAMA_LOG_FORMAT must be either json or text."
    )

LOG_MAX_BYTES = _environment_int(
    "MAMA_LOG_MAX_BYTES",
    10 * 1024 * 1024,
    minimum=1024,
)

LOG_BACKUP_COUNT = _environment_int(
    "MAMA_LOG_BACKUP_COUNT",
    5,
    minimum=1,
)

OBSERVABILITY_REQUEST_ID_HEADER = os.getenv(
    "MAMA_OBSERVABILITY_REQUEST_ID_HEADER",
    "X-Request-ID",
).strip() or "X-Request-ID"

OBSERVABILITY_SLOW_REQUEST_MS = _environment_float(
    "MAMA_OBSERVABILITY_SLOW_REQUEST_MS",
    1000.0,
    minimum=1.0,
)

OBSERVABILITY_ALERT_ERROR_RATE_PERCENT = _environment_float(
    "MAMA_OBSERVABILITY_ALERT_ERROR_RATE_PERCENT",
    5.0,
    minimum=0.0,
)

OBSERVABILITY_ALERT_MIN_REQUESTS = _environment_int(
    "MAMA_OBSERVABILITY_ALERT_MIN_REQUESTS",
    20,
    minimum=1,
)

OBSERVABILITY_ALERT_FAILED_QUEUE_JOBS = _environment_int(
    "MAMA_OBSERVABILITY_ALERT_FAILED_QUEUE_JOBS",
    1,
    minimum=1,
)

OBSERVABILITY_ALERT_STALE_CLAIMS = _environment_int(
    "MAMA_OBSERVABILITY_ALERT_STALE_CLAIMS",
    1,
    minimum=1,
)


# =====================================================
# Directories
# =====================================================

DATA_DIR = _environment_path(
    "MAMA_DATA_DIR",
    BASE_DIR / "data",
)
DATABASE_DIR = _environment_path(
    "MAMA_DATABASE_DIR",
    BASE_DIR / "app" / "database",
)
LOG_DIR = _environment_path(
    "MAMA_LOG_DIR",
    BASE_DIR / "logs",
)
SCREENSHOT_DIR = _environment_path(
    "MAMA_SCREENSHOT_DIR",
    BASE_DIR / "screenshots",
)
CACHE_DIR = _environment_path(
    "MAMA_CACHE_DIR",
    BASE_DIR / "cache",
)
MODEL_DIR = _environment_path(
    "MAMA_MODEL_DIR",
    BASE_DIR / "models",
)
TEMP_DIR = _environment_path(
    "MAMA_TEMP_DIR",
    BASE_DIR / "temp",
)


# =====================================================
# Database
# =====================================================

DATABASE_NAME = "mama_ai.db"
DATABASE_PATH = DATABASE_DIR / DATABASE_NAME


# =====================================================
# Database Migration and Recovery
# =====================================================

DATABASE_MIGRATIONS_ENABLED = _environment_bool(
    "MAMA_DATABASE_MIGRATIONS_ENABLED",
    True,
)

DATABASE_BACKUP_ENABLED = _environment_bool(
    "MAMA_DATABASE_BACKUP_ENABLED",
    True,
)

_database_backup_dir_value = Path(
    os.getenv(
        "MAMA_DATABASE_BACKUP_DIR",
        str(DATA_DIR / "backups"),
    )
).expanduser()

DATABASE_BACKUP_DIR = (
    _database_backup_dir_value
    if _database_backup_dir_value.is_absolute()
    else BASE_DIR / _database_backup_dir_value
).resolve()

DATABASE_BACKUP_RETENTION_COUNT = _environment_int(
    "MAMA_DATABASE_BACKUP_RETENTION_COUNT",
    14,
    minimum=1,
)

DATABASE_BACKUP_INTERVAL_SECONDS = _environment_int(
    "MAMA_DATABASE_BACKUP_INTERVAL_SECONDS",
    21600,
    minimum=60,
)

DATABASE_BACKUP_MIN_INTERVAL_SECONDS = _environment_int(
    "MAMA_DATABASE_BACKUP_MIN_INTERVAL_SECONDS",
    3600,
    minimum=60,
)

DATABASE_BACKUP_ON_STARTUP = _environment_bool(
    "MAMA_DATABASE_BACKUP_ON_STARTUP",
    False,
)

DATABASE_INTEGRITY_CHECK_MODE = os.getenv(
    "MAMA_DATABASE_INTEGRITY_CHECK_MODE",
    "quick",
).strip().lower() or "quick"

if DATABASE_INTEGRITY_CHECK_MODE not in {"quick", "full"}:
    raise ValueError(
        "MAMA_DATABASE_INTEGRITY_CHECK_MODE must be quick or full."
    )

os.makedirs(DATABASE_BACKUP_DIR, exist_ok=True)


# =====================================================
# AI
# =====================================================

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "",
).strip()

DEFAULT_AI_MODEL = os.getenv(
    "AI_MODEL",
    "gemini-2.5-flash",
).strip() or "gemini-2.5-flash"

AI_TIMEOUT = 60
AI_RETRIES = 5


# =====================================================
# Vision
# =====================================================

YOLO_MODEL = "yolov8n.pt"
OCR_LANGUAGE = "eng"


# =====================================================
# Voice
# =====================================================

WAKE_WORD = "hello mama"
VOICE_LANGUAGE = "en"


# =====================================================
# Execution
# =====================================================

MAX_PLAN_STEPS = 20
COMMAND_TIMEOUT = 30


# =====================================================
# Learning
# =====================================================

MAX_MEMORY_RESULTS = 5
MAX_EXPERIENCE_RESULTS = 5


# =====================================================
# Create Required Folders
# =====================================================

REQUIRED_FOLDERS = [
    DATA_DIR,
    DATABASE_DIR,
    LOG_DIR,
    SCREENSHOT_DIR,
    CACHE_DIR,
    MODEL_DIR,
    TEMP_DIR,
]

for folder in REQUIRED_FOLDERS:
    os.makedirs(
        folder,
        exist_ok=True,
    )