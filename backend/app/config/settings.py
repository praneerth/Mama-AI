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

ENVIRONMENT = os.getenv(
    "ENVIRONMENT",
    "development",
).strip() or "development"

DEBUG = _environment_bool(
    "DEBUG",
    True,
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
# Directories
# =====================================================

DATA_DIR = BASE_DIR / "data"
DATABASE_DIR = BASE_DIR / "app" / "database"
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
CACHE_DIR = BASE_DIR / "cache"
MODEL_DIR = BASE_DIR / "models"
TEMP_DIR = BASE_DIR / "temp"


# =====================================================
# Database
# =====================================================

DATABASE_NAME = "mama_ai.db"
DATABASE_PATH = DATABASE_DIR / DATABASE_NAME


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
