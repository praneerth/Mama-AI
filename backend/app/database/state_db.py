"""
Persistent SQLite storage for Mama AI task and approval state.

This module uses the existing Mama AI SQLite database and does not
introduce a second database framework.
"""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.database.database import DATABASE_PATH


TASK_TABLE = "task_state"
APPROVAL_TABLE = "approval_state"


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)

    to_dict = getattr(value, "to_dict", None)

    if callable(to_dict):
        data = to_dict()

        if not isinstance(data, Mapping):
            raise TypeError("to_dict() must return a mapping.")

        return dict(data)

    raise TypeError(
        "Stored values must be mappings or provide to_dict()."
    )


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _json_load(
    value: str | None,
    default: Any,
) -> Any:
    if value is None or value == "":
        return default

    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class SQLiteStateStore:
    """
    SQLite-backed persistence for production task and approval state.
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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")

        return connection

    def initialize(self) -> None:
        database_file = Path(self.database_path)
        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")

            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {TASK_TABLE} (
                    task_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL DEFAULT 'local-user',
                    command TEXT NOT NULL,
                    source TEXT NOT NULL,
                    autonomy_level INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    output_json TEXT,
                    error TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS
                    idx_task_state_status
                ON {TASK_TABLE}(status);

                CREATE INDEX IF NOT EXISTS
                    idx_task_state_created_at
                ON {TASK_TABLE}(created_at DESC);

                CREATE TABLE IF NOT EXISTS {APPROVAL_TABLE} (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    consumed_at TEXT,
                    token_hash TEXT,
                    FOREIGN KEY(task_id)
                        REFERENCES {TASK_TABLE}(task_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_approval_state_task_id
                ON {APPROVAL_TABLE}(task_id);

                CREATE INDEX IF NOT EXISTS
                    idx_approval_state_owner_status
                ON {APPROVAL_TABLE}(owner_id, status);

                CREATE INDEX IF NOT EXISTS
                    idx_approval_state_created_at
                ON {APPROVAL_TABLE}(created_at DESC);
                """
            )

            task_columns = {
                row["name"]
                for row in connection.execute(
                    f"PRAGMA table_info({TASK_TABLE})"
                ).fetchall()
            }

            if "owner_id" not in task_columns:
                connection.execute(
                    f"""
                    ALTER TABLE {TASK_TABLE}
                    ADD COLUMN owner_id TEXT NOT NULL
                    DEFAULT 'local-user'
                    """
                )

            connection.execute(
                f"""
                UPDATE {TASK_TABLE}
                SET owner_id = 'local-user'
                WHERE owner_id IS NULL
                   OR TRIM(owner_id) = ''
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

            if "task_queue" in tables:
                connection.execute(
                    f"""
                    UPDATE {TASK_TABLE}
                    SET owner_id = (
                        SELECT owner_id
                        FROM task_queue
                        WHERE task_queue.task_id =
                              {TASK_TABLE}.task_id
                    )
                    WHERE EXISTS (
                        SELECT 1
                        FROM task_queue
                        WHERE task_queue.task_id =
                              {TASK_TABLE}.task_id
                    )
                    """
                )

            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    idx_task_state_owner_status
                ON {TASK_TABLE}(owner_id, status)
                """
            )

    def save_task(self, record: Any) -> None:
        data = _to_mapping(record)

        required_fields = {
            "task_id",
            "owner_id",
            "command",
            "source",
            "autonomy_level",
            "risk_level",
            "status",
            "created_at",
            "updated_at",
        }

        missing = required_fields.difference(data)

        if missing:
            raise ValueError(
                "Task record is missing fields: "
                + ", ".join(sorted(missing))
            )

        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO {TASK_TABLE} (
                    task_id,
                    owner_id,
                    command,
                    source,
                    autonomy_level,
                    risk_level,
                    status,
                    message,
                    output_json,
                    error,
                    evidence_json,
                    created_at,
                    updated_at,
                    started_at,
                    finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    command = excluded.command,
                    source = excluded.source,
                    autonomy_level = excluded.autonomy_level,
                    risk_level = excluded.risk_level,
                    status = excluded.status,
                    message = excluded.message,
                    output_json = excluded.output_json,
                    error = excluded.error,
                    evidence_json = excluded.evidence_json,
                    updated_at = excluded.updated_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at
                """,
                (
                    str(data["task_id"]),
                    self._validate_text(
                        data["owner_id"],
                        "Owner ID",
                    ),
                    str(data["command"]),
                    str(data["source"]),
                    int(data["autonomy_level"]),
                    str(data["risk_level"]),
                    str(data["status"]),
                    str(data.get("message", "")),
                    _json_dump(data.get("output")),
                    (
                        str(data["error"])
                        if data.get("error") is not None
                        else None
                    ),
                    _json_dump(data.get("evidence", [])),
                    str(data["created_at"]),
                    str(data["updated_at"]),
                    (
                        str(data["started_at"])
                        if data.get("started_at") is not None
                        else None
                    ),
                    (
                        str(data["finished_at"])
                        if data.get("finished_at") is not None
                        else None
                    ),
                ),
            )

    def get_task(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        parameters: list[Any] = [task_id]
        owner_clause = ""

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )
            owner_clause = " AND owner_id = ?"
            parameters.append(owner_id)

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {TASK_TABLE}
                WHERE task_id = ?{owner_clause}
                """,
                tuple(parameters),
            ).fetchone()

        return self._task_row_to_dict(row)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)

        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            status = self._validate_text(
                status,
                "Task status",
            )
            conditions.append("status = ?")
            parameters.append(status)

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )
            conditions.append("owner_id = ?")
            parameters.append(owner_id)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        parameters.append(limit)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {TASK_TABLE}
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [
            self._task_row_to_dict(row)
            for row in rows
        ]

    def save_approval(self, record: Any) -> None:
        data = _to_mapping(record)

        token_hash = getattr(
            record,
            "token_hash",
            data.get("token_hash"),
        )

        required_fields = {
            "approval_id",
            "task_id",
            "owner_id",
            "command",
            "risk_level",
            "status",
            "created_at",
            "expires_at",
        }

        missing = required_fields.difference(data)

        if missing:
            raise ValueError(
                "Approval record is missing fields: "
                + ", ".join(sorted(missing))
            )

        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO {APPROVAL_TABLE} (
                    approval_id,
                    task_id,
                    owner_id,
                    command,
                    risk_level,
                    reasons_json,
                    status,
                    created_at,
                    expires_at,
                    decided_at,
                    consumed_at,
                    token_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    owner_id = excluded.owner_id,
                    command = excluded.command,
                    risk_level = excluded.risk_level,
                    reasons_json = excluded.reasons_json,
                    status = excluded.status,
                    expires_at = excluded.expires_at,
                    decided_at = excluded.decided_at,
                    consumed_at = excluded.consumed_at,
                    token_hash = excluded.token_hash
                """,
                (
                    str(data["approval_id"]),
                    str(data["task_id"]),
                    str(data["owner_id"]),
                    str(data["command"]),
                    str(data["risk_level"]),
                    _json_dump(data.get("reasons", [])),
                    str(data["status"]),
                    str(data["created_at"]),
                    str(data["expires_at"]),
                    (
                        str(data["decided_at"])
                        if data.get("decided_at") is not None
                        else None
                    ),
                    (
                        str(data["consumed_at"])
                        if data.get("consumed_at") is not None
                        else None
                    ),
                    (
                        str(token_hash)
                        if token_hash is not None
                        else None
                    ),
                ),
            )

    def get_approval(
        self,
        approval_id: str,
    ) -> dict[str, Any] | None:
        approval_id = self._validate_text(
            approval_id,
            "Approval ID",
        )

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {APPROVAL_TABLE}
                WHERE approval_id = ?
                """,
                (approval_id,),
            ).fetchone()

        return self._approval_row_to_dict(row)

    def list_approvals(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)

        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            status = self._validate_text(
                status,
                "Approval status",
            )
            conditions.append("status = ?")
            parameters.append(status)

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
                "WHERE " + " AND ".join(conditions)
            )

        parameters.append(limit)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {APPROVAL_TABLE}
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [
            self._approval_row_to_dict(row)
            for row in rows
        ]

    def delete_task(self, task_id: str) -> bool:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"""
                DELETE FROM {TASK_TABLE}
                WHERE task_id = ?
                """,
                (task_id,),
            )

            return cursor.rowcount > 0

    def clear(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"DELETE FROM {APPROVAL_TABLE}"
            )
            connection.execute(
                f"DELETE FROM {TASK_TABLE}"
            )

    @staticmethod
    def _task_row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "task_id": row["task_id"],
            "owner_id": row["owner_id"],
            "command": row["command"],
            "source": row["source"],
            "autonomy_level": row["autonomy_level"],
            "risk_level": row["risk_level"],
            "status": row["status"],
            "message": row["message"],
            "output": _json_load(
                row["output_json"],
                None,
            ),
            "error": row["error"],
            "evidence": _json_load(
                row["evidence_json"],
                [],
            ),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _approval_row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "approval_id": row["approval_id"],
            "task_id": row["task_id"],
            "owner_id": row["owner_id"],
            "command": row["command"],
            "risk_level": row["risk_level"],
            "reasons": _json_load(
                row["reasons_json"],
                [],
            ),
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "decided_at": row["decided_at"],
            "consumed_at": row["consumed_at"],
            "token_hash": row["token_hash"],
        }

    @staticmethod
    def _validate_text(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text.")

        value = value.strip()

        if not value:
            raise ValueError(f"{field_name} cannot be empty.")

        return value

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if not isinstance(limit, int):
            raise TypeError("Limit must be an integer.")

        if limit < 1 or limit > 1000:
            raise ValueError(
                "Limit must be between 1 and 1000."
            )

        return limit


state_store = SQLiteStateStore()


__all__ = [
    "APPROVAL_TABLE",
    "SQLiteStateStore",
    "TASK_TABLE",
    "state_store",
]