"""
Central logging configuration for Mama AI.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import settings


LOGGER_NAME = "mama_ai"

LOG_DIR = Path(getattr(settings, "LOG_DIR", Path.cwd() / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "mama_ai.log"

LOG_LEVEL = (
    logging.DEBUG
    if getattr(settings, "DEBUG", False)
    else logging.INFO
)


logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(LOG_LEVEL)
logger.propagate = False


if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def get_logger(module_name: str | None = None) -> logging.Logger:
    if module_name:
        return logger.getChild(module_name)

    return logger


__all__ = ["logger", "get_logger"]