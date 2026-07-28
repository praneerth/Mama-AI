"""
Persistent API idempotency storage for Mama AI.

The store prevents duplicate side effects when a trusted client retries
the same HTTP request with the same Idempotency-Key. Raw idempotency
keys and complete request bodies are never written to SQLite; only
SHA-256 fingerprints are persisted.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database.database import DATABASE_PATH


IDEMPOTENCY_TABLE = "api_idempotency"

IDEMPOTENCY_STATUSES = {
    "processing",
    "completed",
    "failed",
}

DEFAULT_EXPIRY_SECONDS = 86400
MINIMUM_KEY_LENGTH = 16
MAXIMUM_KEY_LENGTH = 255
MAXIMUM_RESPONSE_BYTES = 262144


class IdempotencyConflictError(ValueError):
    """The same idempotency key was reused for another request."""


class IdempotencyStateError(RuntimeError):
    """The idempotency record cannot perform the requested transition."""


def utc_datetime() -> datetime:
    """Return a timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    """
    Serialize a value deterministically.

    This representation is used only to calculate fingerprints. It is
    never stored as the original request body.
    """

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    except (TypeError, ValueError) as exc:
        raise TypeError(
            "Request payload must be JSON serializable."
        ) from exc


def fingerprint_idempotency_key(
    idempotency_key: str,
) -> str:
    """Return a non-reversible fingerprint for an idempotency key."""

    key = SQLiteIdempotencyStore._validate_idempotency_key(
        idempotency_key
    )

    digest = hashlib.sha256(
        (
            "mama-ai:idempotency-key:"
            + key
        ).encode("utf-8")
    ).hexdigest()

    return digest


def fingerprint_request_payload(
    request_payload: Any,
) -> str:
    """Return a deterministic fingerprint without storing the payload."""

    canonical = _canonical_json(
        request_payload
    )

    return hashlib.sha256(
        (
            "mama-ai:idempotency-request:"
            + canonical
        ).encode("utf-8")
    ).hexdigest()


def _json_dump_response(
    response_body: Mapping[str, Any] | None,
) -> str | None:
    if response_body is None:
        return None

    if not isinstance(
        response_body,
        Mapping,
    ):
        raise TypeError(
            "Stored idempotent response must be a mapping."
        )

    try:
        encoded = json.dumps(
            dict(response_body),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    except (TypeError, ValueError) as exc:
        raise TypeError(
            "Stored idempotent response must be JSON serializable."
        ) from exc

    if (
        len(
            encoded.encode("utf-8")
        )
        > MAXIMUM_RESPONSE_BYTES
    ):
        raise ValueError(
            "Stored idempotent response exceeds "
            f"{MAXIMUM_RESPONSE_BYTES} bytes."
        )

    return encoded


def _json_load_response(
    value: str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None

    try:
        loaded = json.loads(value)

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(loaded, dict):
        return None

    return loaded


class SQLiteIdempotencyStore:
    """
    Atomic SQLite-backed idempotency record store.

    Records are scoped by authenticated owner, HTTP method, request
    path, and key fingerprint. Reusing a key with a different request
    fingerprint raises :class:`IdempotencyConflictError`.
    """

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        *,
        clock: Callable[[], datetime] | None = None,
        initialize: bool = True,
    ) -> None:
        self.database_path = str(
            database_path
        )
        self._clock = (
            clock
            if clock is not None
            else utc_datetime
        )

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
        database_file = Path(
            self.database_path
        )
        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with closing(self._connect()) as connection, connection:
            connection.execute(
                "PRAGMA journal_mode = WAL"
            )
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {IDEMPOTENCY_TABLE} (
                        sequence_id INTEGER
                            PRIMARY KEY AUTOINCREMENT,
                        record_id TEXT NOT NULL UNIQUE,
                        key_fingerprint TEXT NOT NULL,
                        owner_id TEXT NOT NULL,
                        request_method TEXT NOT NULL,
                        request_path TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        status TEXT NOT NULL
                            CHECK (
                                status IN (
                                    'processing',
                                    'completed',
                                    'failed'
                                )
                            ),
                        response_status_code INTEGER
                            CHECK (
                                response_status_code IS NULL
                                OR response_status_code
                                    BETWEEN 100 AND 599
                            ),
                        response_json TEXT,
                        error_code TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        UNIQUE (
                            owner_id,
                            request_method,
                            request_path,
                            key_fingerprint
                        )
                    );

                CREATE INDEX IF NOT EXISTS
                    idx_idempotency_expiry
                ON {IDEMPOTENCY_TABLE}(
                    expires_at
                );

                CREATE INDEX IF NOT EXISTS
                    idx_idempotency_owner_status
                ON {IDEMPOTENCY_TABLE}(
                    owner_id,
                    status,
                    updated_at DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_idempotency_record
                ON {IDEMPOTENCY_TABLE}(
                    record_id
                );
                """
            )

    def reserve(
        self,
        *,
        idempotency_key: str,
        owner_id: str,
        request_method: str,
        request_path: str,
        request_payload: Any,
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    ) -> dict[str, Any]:
        """
        Atomically reserve an idempotency key.

        The returned dictionary contains ``created=True`` for a new
        processing record and ``created=False`` when the same request
        already owns the key.
        """

        key_fingerprint = (
            fingerprint_idempotency_key(
                idempotency_key
            )
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
            256,
        )
        request_method = (
            self._validate_method(
                request_method
            )
        )
        request_path = self._validate_text(
            request_path,
            "Request path",
            1000,
        )
        request_fingerprint = (
            fingerprint_request_payload(
                request_payload
            )
        )
        expiry_seconds = (
            self._validate_expiry(
                expiry_seconds
            )
        )

        now = self._now()
        now_text = now.isoformat()
        expires_at = (
            now
            + timedelta(
                seconds=expiry_seconds
            )
        ).isoformat()

        connection = self._connect()

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            connection.execute(
                f"""
                DELETE FROM {IDEMPOTENCY_TABLE}
                WHERE
                    owner_id = ?
                    AND request_method = ?
                    AND request_path = ?
                    AND key_fingerprint = ?
                    AND expires_at <= ?
                """,
                (
                    owner_id,
                    request_method,
                    request_path,
                    key_fingerprint,
                    now_text,
                ),
            )

            existing = self._select_record(
                connection,
                owner_id=owner_id,
                request_method=request_method,
                request_path=request_path,
                key_fingerprint=(
                    key_fingerprint
                ),
            )

            if existing is not None:
                if (
                    existing[
                        "request_fingerprint"
                    ]
                    != request_fingerprint
                ):
                    raise IdempotencyConflictError(
                        "The Idempotency-Key was already "
                        "used for a different request."
                    )

                connection.commit()

                result = self._row_to_dict(
                    existing
                )
                result["created"] = False
                return result

            record_id = uuid4().hex

            connection.execute(
                f"""
                INSERT INTO {IDEMPOTENCY_TABLE} (
                    record_id,
                    key_fingerprint,
                    owner_id,
                    request_method,
                    request_path,
                    request_fingerprint,
                    status,
                    response_status_code,
                    response_json,
                    error_code,
                    created_at,
                    updated_at,
                    expires_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?,
                    'processing',
                    NULL,
                    NULL,
                    NULL,
                    ?, ?, ?
                )
                """,
                (
                    record_id,
                    key_fingerprint,
                    owner_id,
                    request_method,
                    request_path,
                    request_fingerprint,
                    now_text,
                    now_text,
                    expires_at,
                ),
            )

            created = self._select_record(
                connection,
                owner_id=owner_id,
                request_method=request_method,
                request_path=request_path,
                key_fingerprint=(
                    key_fingerprint
                ),
            )

            connection.commit()

            if created is None:
                raise RuntimeError(
                    "Reserved idempotency record "
                    "could not be loaded."
                )

            result = self._row_to_dict(
                created
            )
            result["created"] = True
            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def get(
        self,
        *,
        idempotency_key: str,
        owner_id: str,
        request_method: str,
        request_path: str,
    ) -> dict[str, Any] | None:
        """Return one unexpired idempotency record."""

        key_fingerprint = (
            fingerprint_idempotency_key(
                idempotency_key
            )
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
            256,
        )
        request_method = (
            self._validate_method(
                request_method
            )
        )
        request_path = self._validate_text(
            request_path,
            "Request path",
            1000,
        )
        now_text = self._now().isoformat()

        connection = self._connect()

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            connection.execute(
                f"""
                DELETE FROM {IDEMPOTENCY_TABLE}
                WHERE expires_at <= ?
                """,
                (now_text,),
            )

            row = self._select_record(
                connection,
                owner_id=owner_id,
                request_method=request_method,
                request_path=request_path,
                key_fingerprint=(
                    key_fingerprint
                ),
            )

            connection.commit()
            return self._row_to_dict(
                row
            )

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def complete(
        self,
        *,
        idempotency_key: str,
        owner_id: str,
        request_method: str,
        request_path: str,
        response_status_code: int,
        response_body: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Store the successful HTTP response for later replay."""

        return self._finish(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=request_method,
            request_path=request_path,
            status="completed",
            response_status_code=(
                response_status_code
            ),
            response_body=response_body,
            error_code=None,
        )

    def fail(
        self,
        *,
        idempotency_key: str,
        owner_id: str,
        request_method: str,
        request_path: str,
        response_status_code: int,
        response_body: Mapping[str, Any],
        error_code: str,
    ) -> dict[str, Any]:
        """Store a stable failure response for later replay."""

        error_code = self._validate_text(
            error_code,
            "Idempotency error code",
            256,
        )

        return self._finish(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=request_method,
            request_path=request_path,
            status="failed",
            response_status_code=(
                response_status_code
            ),
            response_body=response_body,
            error_code=error_code,
        )

    def _finish(
        self,
        *,
        idempotency_key: str,
        owner_id: str,
        request_method: str,
        request_path: str,
        status: str,
        response_status_code: int,
        response_body: Mapping[str, Any],
        error_code: str | None,
    ) -> dict[str, Any]:
        key_fingerprint = (
            fingerprint_idempotency_key(
                idempotency_key
            )
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
            256,
        )
        request_method = (
            self._validate_method(
                request_method
            )
        )
        request_path = self._validate_text(
            request_path,
            "Request path",
            1000,
        )
        status = self._validate_status(
            status
        )
        response_status_code = (
            self._validate_status_code(
                response_status_code
            )
        )
        response_json = (
            _json_dump_response(
                response_body
            )
        )
        now_text = self._now().isoformat()

        connection = self._connect()

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            current = self._select_record(
                connection,
                owner_id=owner_id,
                request_method=request_method,
                request_path=request_path,
                key_fingerprint=(
                    key_fingerprint
                ),
            )

            if current is None:
                raise KeyError(
                    "Idempotency record was not found."
                )

            if current["status"] in {
                "completed",
                "failed",
            }:
                connection.commit()
                return self._row_to_dict(
                    current
                )

            if current["status"] != "processing":
                raise IdempotencyStateError(
                    "Only processing idempotency "
                    "records can be finalized."
                )

            connection.execute(
                f"""
                UPDATE {IDEMPOTENCY_TABLE}
                SET
                    status = ?,
                    response_status_code = ?,
                    response_json = ?,
                    error_code = ?,
                    updated_at = ?
                WHERE record_id = ?
                """,
                (
                    status,
                    response_status_code,
                    response_json,
                    error_code,
                    now_text,
                    current["record_id"],
                ),
            )

            updated = connection.execute(
                f"""
                SELECT *
                FROM {IDEMPOTENCY_TABLE}
                WHERE record_id = ?
                """,
                (
                    current["record_id"],
                ),
            ).fetchone()

            connection.commit()

            if updated is None:
                raise RuntimeError(
                    "Finalized idempotency record "
                    "could not be loaded."
                )

            return self._row_to_dict(
                updated
            )

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def delete_expired(
        self,
        *,
        limit: int = 1000,
    ) -> int:
        """Delete up to ``limit`` expired records."""

        limit = self._validate_limit(
            limit
        )
        now_text = self._now().isoformat()

        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"""
                DELETE FROM {IDEMPOTENCY_TABLE}
                WHERE sequence_id IN (
                    SELECT sequence_id
                    FROM {IDEMPOTENCY_TABLE}
                    WHERE expires_at <= ?
                    ORDER BY sequence_id ASC
                    LIMIT ?
                )
                """,
                (
                    now_text,
                    limit,
                ),
            )

        return int(
            cursor.rowcount
        )

    def list(
        self,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent idempotency records without raw keys or bodies."""

        limit = self._validate_limit(
            limit
        )
        conditions: list[str] = []
        parameters: list[Any] = [
            self._now().isoformat()
        ]

        conditions.append(
            "expires_at > ?"
        )

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
                256,
            )
            conditions.append(
                "owner_id = ?"
            )
            parameters.append(
                owner_id
            )

        if status is not None:
            status = self._validate_status(
                status
            )
            conditions.append(
                "status = ?"
            )
            parameters.append(
                status
            )

        parameters.append(limit)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {IDEMPOTENCY_TABLE}
                WHERE {" AND ".join(conditions)}
                ORDER BY updated_at DESC
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
        owner_id: str | None = None,
        status: str | None = None,
    ) -> int:
        conditions = [
            "expires_at > ?"
        ]
        parameters: list[Any] = [
            self._now().isoformat()
        ]

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
                256,
            )
            conditions.append(
                "owner_id = ?"
            )
            parameters.append(
                owner_id
            )

        if status is not None:
            status = self._validate_status(
                status
            )
            conditions.append(
                "status = ?"
            )
            parameters.append(
                status
            )

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {IDEMPOTENCY_TABLE}
                WHERE {" AND ".join(conditions)}
                """,
                tuple(parameters),
            ).fetchone()

        return int(
            row["total"]
        )


    def health_summary(
        self,
        *,
        stuck_after_seconds: int = 300,
    ) -> dict[str, Any]:
        """
        Return aggregate idempotency health without exposing keys or bodies.

        Active records are grouped by status. Processing records whose
        updated timestamp is older than the configured threshold are
        reported as stuck. Expired records are counted separately.
        """

        stuck_after_seconds = (
            self._validate_stuck_after(
                stuck_after_seconds
            )
        )

        now = self._now()
        now_text = now.isoformat()
        stuck_before = (
            now
            - timedelta(
                seconds=stuck_after_seconds
            )
        ).isoformat()

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"""
                SELECT
                    SUM(
                        CASE
                            WHEN expires_at > ?
                            THEN 1
                            ELSE 0
                        END
                    ) AS active_total,
                    SUM(
                        CASE
                            WHEN
                                expires_at > ?
                                AND status = 'processing'
                            THEN 1
                            ELSE 0
                        END
                    ) AS processing,
                    SUM(
                        CASE
                            WHEN
                                expires_at > ?
                                AND status = 'completed'
                            THEN 1
                            ELSE 0
                        END
                    ) AS completed,
                    SUM(
                        CASE
                            WHEN
                                expires_at > ?
                                AND status = 'failed'
                            THEN 1
                            ELSE 0
                        END
                    ) AS failed,
                    SUM(
                        CASE
                            WHEN expires_at <= ?
                            THEN 1
                            ELSE 0
                        END
                    ) AS expired,
                    SUM(
                        CASE
                            WHEN
                                expires_at > ?
                                AND status = 'processing'
                                AND updated_at <= ?
                            THEN 1
                            ELSE 0
                        END
                    ) AS stuck_processing,
                    MIN(
                        CASE
                            WHEN
                                expires_at > ?
                                AND status = 'processing'
                            THEN updated_at
                            ELSE NULL
                        END
                    ) AS oldest_processing_at
                FROM {IDEMPOTENCY_TABLE}
                """,
                (
                    now_text,
                    now_text,
                    now_text,
                    now_text,
                    now_text,
                    now_text,
                    stuck_before,
                    now_text,
                ),
            ).fetchone()

        return {
            "total": int(
                row["active_total"] or 0
            ),
            "counts": {
                "processing": int(
                    row["processing"] or 0
                ),
                "completed": int(
                    row["completed"] or 0
                ),
                "failed": int(
                    row["failed"] or 0
                ),
            },
            "expired": int(
                row["expired"] or 0
            ),
            "stuck_processing": int(
                row["stuck_processing"] or 0
            ),
            "stuck_after_seconds": (
                stuck_after_seconds
            ),
            "oldest_processing_at": (
                row["oldest_processing_at"]
            ),
            "checked_at": now_text,
        }

    def clear(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"DELETE FROM {IDEMPOTENCY_TABLE}"
            )

    def _now(self) -> datetime:
        current = self._clock()

        if not isinstance(
            current,
            datetime,
        ):
            raise TypeError(
                "Idempotency clock must return datetime."
            )

        if current.tzinfo is None:
            current = current.replace(
                tzinfo=timezone.utc
            )

        return current.astimezone(
            timezone.utc
        )

    @staticmethod
    def _select_record(
        connection: sqlite3.Connection,
        *,
        owner_id: str,
        request_method: str,
        request_path: str,
        key_fingerprint: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            f"""
            SELECT *
            FROM {IDEMPOTENCY_TABLE}
            WHERE
                owner_id = ?
                AND request_method = ?
                AND request_path = ?
                AND key_fingerprint = ?
            """,
            (
                owner_id,
                request_method,
                request_path,
                key_fingerprint,
            ),
        ).fetchone()

    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "record_id": row["record_id"],
            "key_fingerprint": (
                row["key_fingerprint"]
            ),
            "owner_id": row["owner_id"],
            "request_method": (
                row["request_method"]
            ),
            "request_path": (
                row["request_path"]
            ),
            "request_fingerprint": (
                row["request_fingerprint"]
            ),
            "status": row["status"],
            "response_status_code": (
                row[
                    "response_status_code"
                ]
            ),
            "response_body": (
                _json_load_response(
                    row["response_json"]
                )
            ),
            "error_code": row["error_code"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }

    @staticmethod
    def _validate_idempotency_key(
        value: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                "Idempotency-Key must be text."
            )

        value = value.strip()

        if (
            len(value)
            < MINIMUM_KEY_LENGTH
        ):
            raise ValueError(
                "Idempotency-Key must contain at least "
                f"{MINIMUM_KEY_LENGTH} characters."
            )

        if (
            len(value)
            > MAXIMUM_KEY_LENGTH
        ):
            raise ValueError(
                "Idempotency-Key cannot exceed "
                f"{MAXIMUM_KEY_LENGTH} characters."
            )

        return value

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
    def _validate_method(
        cls,
        request_method: str,
    ) -> str:
        return cls._validate_text(
            request_method,
            "Request method",
            32,
        ).upper()

    @classmethod
    def _validate_status(
        cls,
        status: str,
    ) -> str:
        status = cls._validate_text(
            status,
            "Idempotency status",
            32,
        ).lower()

        if status not in IDEMPOTENCY_STATUSES:
            raise ValueError(
                "Unsupported idempotency status: "
                f"{status}"
            )

        return status

    @staticmethod
    def _validate_status_code(
        status_code: int,
    ) -> int:
        if (
            isinstance(status_code, bool)
            or not isinstance(
                status_code,
                int,
            )
        ):
            raise TypeError(
                "Response status code must be an integer."
            )

        if not 100 <= status_code <= 599:
            raise ValueError(
                "Response status code must be "
                "between 100 and 599."
            )

        return status_code

    @staticmethod
    def _validate_expiry(
        expiry_seconds: int,
    ) -> int:
        if (
            isinstance(expiry_seconds, bool)
            or not isinstance(
                expiry_seconds,
                int,
            )
        ):
            raise TypeError(
                "Idempotency expiry must be an integer."
            )

        if (
            expiry_seconds < 60
            or expiry_seconds > 604800
        ):
            raise ValueError(
                "Idempotency expiry must be between "
                "60 and 604800 seconds."
            )

        return expiry_seconds


    @staticmethod
    def _validate_stuck_after(
        stuck_after_seconds: int,
    ) -> int:
        if (
            isinstance(
                stuck_after_seconds,
                bool,
            )
            or not isinstance(
                stuck_after_seconds,
                int,
            )
        ):
            raise TypeError(
                "Stuck-processing threshold must be an integer."
            )

        if not 1 <= stuck_after_seconds <= 604800:
            raise ValueError(
                "Stuck-processing threshold must be "
                "between 1 and 604800 seconds."
            )

        return stuck_after_seconds

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


idempotency_store = SQLiteIdempotencyStore()


__all__ = [
    "DEFAULT_EXPIRY_SECONDS",
    "IDEMPOTENCY_STATUSES",
    "IDEMPOTENCY_TABLE",
    "IdempotencyConflictError",
    "IdempotencyStateError",
    "SQLiteIdempotencyStore",
    "fingerprint_idempotency_key",
    "fingerprint_request_payload",
    "idempotency_store",
]