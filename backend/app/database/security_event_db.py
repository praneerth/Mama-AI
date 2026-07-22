"""
Persistent append-only security-event audit storage for Mama AI.

Security metadata is sanitized before it is written to SQLite. Raw
bearer tokens, API keys, passwords, cookies, forwarded-for values, and
raw client addresses are never intentionally persisted.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database.database import DATABASE_PATH


SECURITY_EVENT_TABLE = "security_event_audit"

SECURITY_EVENT_TYPES = {
    "authentication_failed",
    "invalid_token",
    "authentication_cooldown_started",
    "authentication_cooldown_blocked",
    "rate_limit_exceeded",
    "owner_mismatch",
    "security_configuration_error",
}

SECURITY_SEVERITIES = {
    "info",
    "warning",
    "error",
    "critical",
}

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_ip",
    "cookie",
    "credentials",
    "gemini_api_key",
    "host",
    "ip",
    "ip_address",
    "mama_api_token",
    "password",
    "remote_addr",
    "secret",
    "set_cookie",
    "token",
    "x_api_key",
    "x_forwarded_for",
}

_BEARER_PATTERN = re.compile(
    r"(?i)\bbearer\s+[^\s,;]+"
)

_MAX_DEPTH = 6
_MAX_ITEMS = 50
_MAX_STRING_LENGTH = 1000


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_key(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value).strip().lower(),
    ).strip("_")


def _is_sensitive_key(value: Any) -> bool:
    normalized = _normalize_key(value)

    if normalized in _SENSITIVE_KEYS:
        return True

    fragments = {
        "authorization",
        "password",
        "secret",
        "token",
        "cookie",
        "api_key",
        "apikey",
        "forwarded_for",
        "client_ip",
        "remote_addr",
        "ip_address",
    }

    return any(
        fragment in normalized
        for fragment in fragments
    )


def _sanitize_string(value: str) -> str:
    value = _BEARER_PATTERN.sub(
        "Bearer [REDACTED]",
        value,
    )

    if len(value) > _MAX_STRING_LENGTH:
        return (
            value[:_MAX_STRING_LENGTH]
            + "...[truncated]"
        )

    return value


def sanitize_metadata(
    value: Any,
    *,
    _depth: int = 0,
) -> Any:
    """Return bounded JSON-safe metadata with sensitive values removed."""

    if _depth >= _MAX_DEPTH:
        return "[MAX_DEPTH]"

    if value is None or isinstance(
        value,
        (bool, int, float),
    ):
        return value

    if isinstance(value, str):
        return _sanitize_string(value)

    if isinstance(value, bytes):
        return "[BYTES_REDACTED]"

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for index, (key, item) in enumerate(
            value.items()
        ):
            if index >= _MAX_ITEMS:
                result["_truncated_items"] = True
                break

            key_text = str(key)[:100]

            if _is_sensitive_key(key_text):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = sanitize_metadata(
                    item,
                    _depth=_depth + 1,
                )

        return result

    if isinstance(
        value,
        Sequence,
    ) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        result = [
            sanitize_metadata(
                item,
                _depth=_depth + 1,
            )
            for item in value[:_MAX_ITEMS]
        ]

        if len(value) > _MAX_ITEMS:
            result.append("[TRUNCATED_ITEMS]")

        return result

    return _sanitize_string(str(value))


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _json_load(
    value: str | None,
) -> dict[str, Any]:
    if not value:
        return {}

    try:
        loaded = json.loads(value)
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return {}

    return loaded if isinstance(loaded, dict) else {}


class SQLiteSecurityEventStore:
    """SQLite-backed append-only security-event audit log."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        *,
        initialize: bool = True,
    ) -> None:
        self.database_path = str(database_path)

        if initialize:
            self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )
        return connection

    def initialize(self) -> None:
        database_file = Path(self.database_path)
        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        event_values = ", ".join(
            f"'{value}'"
            for value in sorted(
                SECURITY_EVENT_TYPES
            )
        )
        severity_values = ", ".join(
            f"'{value}'"
            for value in sorted(
                SECURITY_SEVERITIES
            )
        )

        with self._connect() as connection:
            connection.execute(
                "PRAGMA journal_mode = WAL"
            )
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {SECURITY_EVENT_TABLE} (
                        sequence_id INTEGER
                            PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        event_type TEXT NOT NULL
                            CHECK (
                                event_type IN ({event_values})
                            ),
                        severity TEXT NOT NULL
                            CHECK (
                                severity IN ({severity_values})
                            ),
                        client_ref TEXT,
                        owner_id TEXT,
                        request_method TEXT,
                        request_path TEXT,
                        status_code INTEGER
                            CHECK (
                                status_code IS NULL
                                OR status_code BETWEEN 100 AND 599
                            ),
                        retry_after_seconds INTEGER
                            CHECK (
                                retry_after_seconds IS NULL
                                OR retry_after_seconds >= 0
                            ),
                        message TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{{}}',
                        created_at TEXT NOT NULL
                    );

                CREATE INDEX IF NOT EXISTS
                    idx_security_event_type
                ON {SECURITY_EVENT_TABLE}(
                    event_type,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_security_event_severity
                ON {SECURITY_EVENT_TABLE}(
                    severity,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_security_event_client
                ON {SECURITY_EVENT_TABLE}(
                    client_ref,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_security_event_owner
                ON {SECURITY_EVENT_TABLE}(
                    owner_id,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_security_event_created
                ON {SECURITY_EVENT_TABLE}(
                    created_at DESC
                );
                """
            )

    def append(
        self,
        *,
        event_type: str,
        severity: str,
        client_ref: str | None = None,
        owner_id: str | None = None,
        request_method: str | None = None,
        request_path: str | None = None,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        event_type = self._validate_choice(
            event_type,
            "Security event type",
            SECURITY_EVENT_TYPES,
        )
        severity = self._validate_choice(
            severity,
            "Security severity",
            SECURITY_SEVERITIES,
        ).lower()

        client_ref = self._optional_text(
            client_ref,
            "Client reference",
            256,
        )
        owner_id = self._optional_text(
            owner_id,
            "Owner ID",
            256,
        )

        if request_method is not None:
            request_method = self._validate_text(
                request_method,
                "Request method",
                32,
            ).upper()

        request_path = self._optional_text(
            request_path,
            "Request path",
            1000,
        )
        status_code = self._validate_status_code(
            status_code
        )
        retry_after_seconds = (
            self._validate_retry_after(
                retry_after_seconds
            )
        )
        message = self._optional_text(
            message,
            "Security event message",
            2000,
        )

        if metadata is None:
            metadata_dict: dict[str, Any] = {}
        elif isinstance(metadata, Mapping):
            sanitized = sanitize_metadata(
                dict(metadata)
            )
            metadata_dict = (
                sanitized
                if isinstance(sanitized, dict)
                else {}
            )
        else:
            raise TypeError(
                "Security event metadata must be a mapping."
            )

        if created_at is None:
            created_at = utc_datetime().isoformat()
        else:
            created_at = self._validate_text(
                created_at,
                "Created timestamp",
                100,
            )

        event_id = uuid4().hex
        metadata_json = _json_dump(
            metadata_dict
        )
        owns_connection = connection is None
        active_connection = (
            self._connect()
            if connection is None
            else connection
        )

        try:
            active_connection.execute(
                f"""
                INSERT INTO {SECURITY_EVENT_TABLE} (
                    event_id,
                    event_type,
                    severity,
                    client_ref,
                    owner_id,
                    request_method,
                    request_path,
                    status_code,
                    retry_after_seconds,
                    message,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    severity,
                    client_ref,
                    owner_id,
                    request_method,
                    request_path,
                    status_code,
                    retry_after_seconds,
                    message,
                    metadata_json,
                    created_at,
                ),
            )

            if owns_connection:
                active_connection.commit()
        except Exception:
            if owns_connection:
                active_connection.rollback()
            raise
        finally:
            if owns_connection:
                active_connection.close()

        return {
            "event_id": event_id,
            "event_type": event_type,
            "severity": severity,
            "client_ref": client_ref,
            "owner_id": owner_id,
            "request_method": request_method,
            "request_path": request_path,
            "status_code": status_code,
            "retry_after_seconds": retry_after_seconds,
            "message": message,
            "metadata": metadata_dict,
            "created_at": created_at,
        }

    def get(
        self,
        event_id: str,
    ) -> dict[str, Any] | None:
        event_id = self._validate_text(
            event_id,
            "Security event ID",
            128,
        )

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {SECURITY_EVENT_TABLE}
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def list(
        self,
        *,
        event_type: str | None = None,
        severity: str | None = None,
        client_ref: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)
        conditions: list[str] = []
        parameters: list[Any] = []

        filters = (
            (
                "event_type",
                event_type,
                SECURITY_EVENT_TYPES,
            ),
            (
                "severity",
                severity,
                SECURITY_SEVERITIES,
            ),
        )

        for column, value, choices in filters:
            if value is not None:
                value = self._validate_choice(
                    value,
                    column.replace("_", " ").title(),
                    choices,
                )
                conditions.append(
                    f"{column} = ?"
                )
                parameters.append(
                    value.lower()
                    if column == "severity"
                    else value
                )

        for column, value, label in (
            (
                "client_ref",
                client_ref,
                "Client reference",
            ),
            (
                "owner_id",
                owner_id,
                "Owner ID",
            ),
        ):
            if value is not None:
                value = self._validate_text(
                    value,
                    label,
                    256,
                )
                conditions.append(
                    f"{column} = ?"
                )
                parameters.append(value)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {SECURITY_EVENT_TABLE}
                {where_clause}
                ORDER BY sequence_id DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    def count(
        self,
        *,
        event_type: str | None = None,
        severity: str | None = None,
        client_ref: str | None = None,
        owner_id: str | None = None,
    ) -> int:
        conditions: list[str] = []
        parameters: list[Any] = []

        filters = (
            (
                "event_type",
                event_type,
                SECURITY_EVENT_TYPES,
            ),
            (
                "severity",
                severity,
                SECURITY_SEVERITIES,
            ),
        )

        for column, value, choices in filters:
            if value is not None:
                value = self._validate_choice(
                    value,
                    column.replace("_", " ").title(),
                    choices,
                )
                conditions.append(
                    f"{column} = ?"
                )
                parameters.append(
                    value.lower()
                    if column == "severity"
                    else value
                )

        for column, value, label in (
            (
                "client_ref",
                client_ref,
                "Client reference",
            ),
            (
                "owner_id",
                owner_id,
                "Owner ID",
            ),
        ):
            if value is not None:
                value = self._validate_text(
                    value,
                    label,
                    256,
                )
                conditions.append(
                    f"{column} = ?"
                )
                parameters.append(value)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {SECURITY_EVENT_TABLE}
                {where_clause}
                """,
                tuple(parameters),
            ).fetchone()

        return int(row["total"])

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM {SECURITY_EVENT_TABLE}"
            )

    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "severity": row["severity"],
            "client_ref": row["client_ref"],
            "owner_id": row["owner_id"],
            "request_method": row["request_method"],
            "request_path": row["request_path"],
            "status_code": row["status_code"],
            "retry_after_seconds": (
                row["retry_after_seconds"]
            ),
            "message": row["message"],
            "metadata": _json_load(
                row["metadata_json"]
            ),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _validate_text(
        value: str,
        field_name: str,
        maximum_length: int,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be text."
            )

        value = value.strip()

        if not value:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        if len(value) > maximum_length:
            raise ValueError(
                f"{field_name} cannot exceed "
                f"{maximum_length} characters."
            )

        return value

    @classmethod
    def _optional_text(
        cls,
        value: str | None,
        field_name: str,
        maximum_length: int,
    ) -> str | None:
        if value is None:
            return None

        return cls._validate_text(
            value,
            field_name,
            maximum_length,
        )

    @classmethod
    def _validate_choice(
        cls,
        value: str,
        field_name: str,
        choices: set[str],
    ) -> str:
        value = cls._validate_text(
            value,
            field_name,
            100,
        ).lower()

        if value not in choices:
            raise ValueError(
                f"Unsupported {field_name.lower()}: {value}"
            )

        return value

    @staticmethod
    def _validate_status_code(
        status_code: int | None,
    ) -> int | None:
        if status_code is None:
            return None

        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
        ):
            raise TypeError(
                "Status code must be an integer."
            )

        if not 100 <= status_code <= 599:
            raise ValueError(
                "Status code must be between 100 and 599."
            )

        return status_code

    @staticmethod
    def _validate_retry_after(
        retry_after_seconds: int | None,
    ) -> int | None:
        if retry_after_seconds is None:
            return None

        if (
            isinstance(retry_after_seconds, bool)
            or not isinstance(
                retry_after_seconds,
                int,
            )
        ):
            raise TypeError(
                "Retry-after seconds must be an integer."
            )

        if retry_after_seconds < 0:
            raise ValueError(
                "Retry-after seconds cannot be negative."
            )

        return retry_after_seconds

    @staticmethod
    def _validate_limit(
        limit: int,
    ) -> int:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
        ):
            raise TypeError(
                "Limit must be an integer."
            )

        if not 1 <= limit <= 1000:
            raise ValueError(
                "Limit must be between 1 and 1000."
            )

        return limit


security_event_store = SQLiteSecurityEventStore()


security_audit_logger = logging.getLogger(
    "mama_ai.security_audit"
)


def record_security_event_safely(
    **event: Any,
) -> bool:
    """
    Persist one security event without breaking request processing.

    Only the event type and exception class are logged on failure.
    Event metadata and credentials are never included in this fallback
    log message.
    """

    try:
        security_event_store.append(
            **event
        )

    except Exception as exc:
        security_audit_logger.error(
            "Security event persistence failed | "
            "event_type=%s | error_type=%s",
            str(
                event.get(
                    "event_type",
                    "unknown",
                )
            ),
            type(exc).__name__,
        )

        return False

    return True


__all__ = [
    "SECURITY_EVENT_TABLE",
    "SECURITY_EVENT_TYPES",
    "SECURITY_SEVERITIES",
    "SQLiteSecurityEventStore",
    "record_security_event_safely",
    "sanitize_metadata",
    "security_event_store",
]