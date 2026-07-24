"""
Persistent execution-attempt audit storage for Mama AI.

This module uses the existing Mama AI SQLite database. It records queue
lifecycle events without introducing a second database framework.

Queue operations can pass their active SQLite connection to append()
so an audit event is committed or rolled back in the same transaction
as the queue-state change.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database.database import DATABASE_PATH


ATTEMPT_AUDIT_TABLE = "task_attempt_audit"

ATTEMPT_EVENT_TYPES = {
    "enqueued",
    "claimed",
    "retry_scheduled",
    "failed",
    "manually_retried",
    "completed",
    "cancelled",
    "reconciled",
}

AUDIT_QUEUE_STATUSES = {
    "queued",
    "claimed",
    "completed",
    "failed",
    "cancelled",
}


def utc_datetime() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)


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
    if value is None or value == "":
        return {}

    try:
        loaded = json.loads(value)

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return {}

    if not isinstance(loaded, dict):
        return {}

    return loaded


class SQLiteAttemptAuditStore:
    """
    SQLite-backed append-only queue-attempt audit log.

    Audit records are immutable. The store supports using an existing
    SQLite connection so queue state and its audit event can share one
    atomic transaction.
    """

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
        database_file = Path(
            self.database_path
        )

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        event_values = ", ".join(
            f"'{value}'"
            for value in sorted(
                ATTEMPT_EVENT_TYPES
            )
        )

        status_values = ", ".join(
            f"'{value}'"
            for value in sorted(
                AUDIT_QUEUE_STATUSES
            )
        )

        with self._connect() as connection:
            connection.execute(
                "PRAGMA journal_mode = WAL"
            )

            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS
                    {ATTEMPT_AUDIT_TABLE} (
                        sequence_id INTEGER
                            PRIMARY KEY AUTOINCREMENT,
                        audit_id TEXT NOT NULL UNIQUE,
                        task_id TEXT NOT NULL,
                        owner_id TEXT NOT NULL DEFAULT 'local-user',
                        attempt INTEGER NOT NULL
                            CHECK (attempt >= 0),
                        event_type TEXT NOT NULL
                            CHECK (
                                event_type IN (
                                    {event_values}
                                )
                            ),
                        queue_status TEXT NOT NULL
                            CHECK (
                                queue_status IN (
                                    {status_values}
                                )
                            ),
                        worker_id TEXT,
                        message TEXT,
                        error TEXT,
                        metadata_json TEXT NOT NULL
                            DEFAULT '{{}}',
                        created_at TEXT NOT NULL
                    );

                CREATE INDEX IF NOT EXISTS
                    idx_attempt_audit_task
                ON {ATTEMPT_AUDIT_TABLE}(
                    task_id,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_attempt_audit_event
                ON {ATTEMPT_AUDIT_TABLE}(
                    event_type,
                    sequence_id DESC
                );

                CREATE INDEX IF NOT EXISTS
                    idx_attempt_audit_created
                ON {ATTEMPT_AUDIT_TABLE}(
                    created_at DESC
                );
                """
            )

            columns = {
                row["name"]
                for row in connection.execute(
                    f"PRAGMA table_info({ATTEMPT_AUDIT_TABLE})"
                ).fetchall()
            }

            if "owner_id" not in columns:
                connection.execute(
                    f"""
                    ALTER TABLE {ATTEMPT_AUDIT_TABLE}
                    ADD COLUMN owner_id TEXT NOT NULL
                    DEFAULT 'local-user'
                    """
                )

            tables = {
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

            connection.execute(
                f"""
                UPDATE {ATTEMPT_AUDIT_TABLE}
                SET owner_id = 'local-user'
                WHERE owner_id IS NULL
                   OR TRIM(owner_id) = ''
                """
            )

            if "task_queue" in tables:
                connection.execute(
                    f"""
                    UPDATE {ATTEMPT_AUDIT_TABLE}
                    SET owner_id = (
                        SELECT owner_id
                        FROM task_queue
                        WHERE task_queue.task_id =
                              {ATTEMPT_AUDIT_TABLE}.task_id
                    )
                    WHERE EXISTS (
                        SELECT 1
                        FROM task_queue
                        WHERE task_queue.task_id =
                              {ATTEMPT_AUDIT_TABLE}.task_id
                    )
                    """
                )

            if "task_state" in tables:
                connection.execute(
                    f"""
                    UPDATE {ATTEMPT_AUDIT_TABLE}
                    SET owner_id = (
                        SELECT owner_id
                        FROM task_state
                        WHERE task_state.task_id =
                              {ATTEMPT_AUDIT_TABLE}.task_id
                    )
                    WHERE owner_id = 'local-user'
                      AND EXISTS (
                        SELECT 1
                        FROM task_state
                        WHERE task_state.task_id =
                              {ATTEMPT_AUDIT_TABLE}.task_id
                    )
                    """
                )

            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    idx_attempt_audit_owner_created
                ON {ATTEMPT_AUDIT_TABLE}(
                    owner_id,
                    sequence_id DESC
                )
                """
            )

    def append(
        self,
        *,
        task_id: str,
        owner_id: str = "local-user",
        attempt: int,
        event_type: str,
        queue_status: str,
        worker_id: str | None = None,
        message: str | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """
        Append one immutable audit event.

        When connection is supplied, this method does not commit or
        close it. The caller owns the transaction.
        """

        task_id = self._validate_text(
            task_id,
            "Task ID",
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
        )
        attempt = self._validate_attempt(
            attempt
        )
        event_type = self._validate_event_type(
            event_type
        )
        queue_status = self._validate_queue_status(
            queue_status
        )

        if worker_id is not None:
            worker_id = self._validate_text(
                worker_id,
                "Worker ID",
            )

        if message is not None:
            message = str(message).strip() or None

        if error is not None:
            error = str(error).strip() or None

        if metadata is None:
            metadata_dict: dict[str, Any] = {}

        elif isinstance(metadata, Mapping):
            metadata_dict = dict(metadata)

        else:
            raise TypeError(
                "Audit metadata must be a mapping."
            )

        if created_at is None:
            created_at = utc_datetime().isoformat()

        else:
            created_at = self._validate_text(
                created_at,
                "Created timestamp",
            )

        audit_id = uuid4().hex
        metadata_json = _json_dump(
            metadata_dict
        )

        owns_connection = (
            connection is None
        )

        active_connection = (
            self._connect()
            if connection is None
            else connection
        )

        try:
            active_connection.execute(
                f"""
                INSERT INTO {ATTEMPT_AUDIT_TABLE} (
                    audit_id,
                    task_id,
                    owner_id,
                    attempt,
                    event_type,
                    queue_status,
                    worker_id,
                    message,
                    error,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    task_id,
                    owner_id,
                    attempt,
                    event_type,
                    queue_status,
                    worker_id,
                    message,
                    error,
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
            "audit_id": audit_id,
            "task_id": task_id,
            "owner_id": owner_id,
            "attempt": attempt,
            "event_type": event_type,
            "queue_status": queue_status,
            "worker_id": worker_id,
            "message": message,
            "error": error,
            "metadata": metadata_dict,
            "created_at": created_at,
        }

    def get(
        self,
        audit_id: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        audit_id = self._validate_text(
            audit_id,
            "Audit ID",
        )

        parameters: list[Any] = [audit_id]
        owner_clause = ""

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )
            owner_clause = " AND owner_id = ?"
            parameters.append(owner_id)

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {ATTEMPT_AUDIT_TABLE}
                WHERE audit_id = ?{owner_clause}
                """,
                tuple(parameters),
            ).fetchone()

        return self._row_to_dict(row)

    def list(
        self,
        *,
        task_id: str | None = None,
        event_type: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(
            limit
        )

        conditions: list[str] = []
        parameters: list[Any] = []

        if task_id is not None:
            task_id = self._validate_text(
                task_id,
                "Task ID",
            )

            conditions.append(
                "task_id = ?"
            )
            parameters.append(
                task_id
            )

        if event_type is not None:
            event_type = (
                self._validate_event_type(
                    event_type
                )
            )

            conditions.append(
                "event_type = ?"
            )
            parameters.append(
                event_type
            )

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )
            conditions.append("owner_id = ?")
            parameters.append(owner_id)

        where_clause = ""

        if conditions:
            where_clause = (
                "WHERE "
                + " AND ".join(
                    conditions
                )
            )

        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {ATTEMPT_AUDIT_TABLE}
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
        task_id: str | None = None,
        event_type: str | None = None,
        owner_id: str | None = None,
    ) -> int:
        conditions: list[str] = []
        parameters: list[Any] = []

        if task_id is not None:
            task_id = self._validate_text(
                task_id,
                "Task ID",
            )

            conditions.append(
                "task_id = ?"
            )
            parameters.append(
                task_id
            )

        if event_type is not None:
            event_type = (
                self._validate_event_type(
                    event_type
                )
            )

            conditions.append(
                "event_type = ?"
            )
            parameters.append(
                event_type
            )

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )
            conditions.append("owner_id = ?")
            parameters.append(owner_id)

        where_clause = ""

        if conditions:
            where_clause = (
                "WHERE "
                + " AND ".join(
                    conditions
                )
            )

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {ATTEMPT_AUDIT_TABLE}
                {where_clause}
                """,
                tuple(parameters),
            ).fetchone()

        return int(row["total"])

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM {ATTEMPT_AUDIT_TABLE}
                """
            )

    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "audit_id": row["audit_id"],
            "task_id": row["task_id"],
            "owner_id": row["owner_id"],
            "attempt": row["attempt"],
            "event_type": row["event_type"],
            "queue_status": row["queue_status"],
            "worker_id": row["worker_id"],
            "message": row["message"],
            "error": row["error"],
            "metadata": _json_load(
                row["metadata_json"]
            ),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _validate_text(
        value: str,
        field_name: str,
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

        return value

    @staticmethod
    def _validate_attempt(
        attempt: int,
    ) -> int:
        if not isinstance(attempt, int):
            raise TypeError(
                "Attempt must be an integer."
            )

        if attempt < 0:
            raise ValueError(
                "Attempt cannot be negative."
            )

        return attempt

    @staticmethod
    def _validate_event_type(
        event_type: str,
    ) -> str:
        event_type = (
            SQLiteAttemptAuditStore._validate_text(
                event_type,
                "Audit event type",
            )
        )

        if event_type not in ATTEMPT_EVENT_TYPES:
            raise ValueError(
                "Unsupported audit event type: "
                f"{event_type}"
            )

        return event_type

    @staticmethod
    def _validate_queue_status(
        queue_status: str,
    ) -> str:
        queue_status = (
            SQLiteAttemptAuditStore._validate_text(
                queue_status,
                "Queue status",
            )
        )

        if queue_status not in AUDIT_QUEUE_STATUSES:
            raise ValueError(
                "Unsupported queue status: "
                f"{queue_status}"
            )

        return queue_status

    @staticmethod
    def _validate_limit(
        limit: int,
    ) -> int:
        if not isinstance(limit, int):
            raise TypeError(
                "Limit must be an integer."
            )

        if limit < 1 or limit > 1000:
            raise ValueError(
                "Limit must be between 1 and 1000."
            )

        return limit


attempt_audit_store = SQLiteAttemptAuditStore()


__all__ = [
    "ATTEMPT_AUDIT_TABLE",
    "ATTEMPT_EVENT_TYPES",
    "AUDIT_QUEUE_STATUSES",
    "SQLiteAttemptAuditStore",
    "attempt_audit_store",
]