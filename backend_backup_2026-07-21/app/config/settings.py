"""
Mama AI Configuration
Production Settings
"""

from pathlib import Path
import os

# =====================================================
# Project Root
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[2]

# =====================================================
# Application
# =====================================================

APP_NAME = "Mama AI"
APP_VERSION = "1.0.0"
DEBUG = True

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

DEFAULT_AI_MODEL = "gemini-2.5-flash"

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
    os.makedirs(folder, exist_ok=True)