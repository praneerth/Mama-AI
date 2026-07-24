"""Central structured logging configuration for Mama AI."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.observability.context import get_request_id
from app.observability.redaction import redact_text, redact_value

from . import settings


LOGGER_NAME = "mama_ai"
LOG_DIR = Path(getattr(settings, "LOG_DIR", Path.cwd() / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "mama_ai.log"

_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def _log_level() -> int:
    value = str(getattr(settings, "LOG_LEVEL", "INFO")).upper()
    return getattr(logging, value, logging.INFO)


class JsonLogFormatter(logging.Formatter):
    """Serialize logs as redacted single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = str(request_id)
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            if key in {"args", "exc_info", "exc_text", "stack_info"}:
                continue
            payload[key] = redact_value(value, key=key)
        if record.exc_info:
            payload["exception"] = redact_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class TextLogFormatter(logging.Formatter):
    """Human-readable formatter that still redacts free-form messages."""

    def format(self, record: logging.LogRecord) -> str:
        original = record.msg
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
            return super().format(record)
        finally:
            record.msg = original


def configure_logging() -> logging.Logger:
    level = _log_level()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    if getattr(settings, "LOG_FORMAT", "json") == "json":
        formatter: logging.Formatter = JsonLogFormatter()
    else:
        formatter = TextLogFormatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=int(getattr(settings, "LOG_MAX_BYTES", 10 * 1024 * 1024)),
        backupCount=int(getattr(settings, "LOG_BACKUP_COUNT", 5)),
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


logger = configure_logging()


def get_logger(module_name: str | None = None) -> logging.Logger:
    if module_name:
        return logger.getChild(module_name)
    return logger


__all__ = [
    "JsonLogFormatter",
    "TextLogFormatter",
    "configure_logging",
    "get_logger",
    "logger",
]
