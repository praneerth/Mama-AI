"""
Durable SQLite task queue for Mama AI.

The queue stores execution scheduling information. Complete task
details and results remain in the existing task_state table.

Every queue-state transition is written to the persistent attempt audit
log in the same SQLite transaction. A queue update and its audit event
therefore either both commit or both roll back.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.database.attempt_audit_db import (
    SQLiteAttemptAuditStore,
)
from app.database.database import DATABASE_PATH


QUEUE_TABLE = "task_queue"

QUEUE_STATUSES = {
    "queued",
    "claimed",
    "completed",
    "failed",
    "cancelled",
}


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteTaskQueueStore:
    """Atomic SQLite storage for durable Mama AI jobs."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        *,
        clock: Callable[[], datetime] | None = None,
        audit_store: SQLiteAttemptAuditStore | None = None,
        initialize: bool = True,
    ) -> None:
        self.database_path = str(database_path)
        self._clock = clock or utc_datetime
        self._audit = (
            audit_store
            if audit_store is not None
            else SQLiteAttemptAuditStore(
                self.database_path,
                initialize=initialize,
            )
        )

        if initialize:
            self.initialize()

    @property
    def audit_store(self) -> SQLiteAttemptAuditStore:
        """Return the audit store used by this queue."""

        return self._audit

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    def initialize(self) -> None:
        database_file = Path(self.database_path)

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._audit.initialize()

        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")

            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {QUEUE_TABLE} (
                    task_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (
                            status IN (
                                'queued',
                                'claimed',
                                'completed',
                                'failed',
                                'cancelled'
                            )
                        ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at TEXT NOT NULL,
                    lease_expires_at TEXT,
                    worker_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS
                    idx_task_queue_claim
                ON {QUEUE_TABLE}(
                    status,
                    available_at,
                    created_at
                );

                CREATE INDEX IF NOT EXISTS
                    idx_task_queue_lease
                ON {QUEUE_TABLE}(
                    status,
                    lease_expires_at
                );

                CREATE INDEX IF NOT EXISTS
                    idx_task_queue_owner
                ON {QUEUE_TABLE}(
                    owner_id,
                    status
                );
                """
            )

    def enqueue(
        self,
        task_id: str,
        *,
        owner_id: str = "local-user",
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> dict[str, Any]:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
        )

        self._validate_max_attempts(max_attempts)
        self._validate_delay(delay_seconds)

        now = self._now()

        available_at = (
            now + timedelta(seconds=delay_seconds)
        )

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute(
                f"""
                INSERT INTO {QUEUE_TABLE} (
                    task_id,
                    owner_id,
                    status,
                    attempts,
                    max_attempts,
                    available_at,
                    lease_expires_at,
                    worker_id,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 'queued', 0, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    task_id,
                    owner_id,
                    max_attempts,
                    available_at.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )

            self._audit.append(
                task_id=task_id,
                attempt=0,
                event_type="enqueued",
                queue_status="queued",
                message="Task added to the durable queue.",
                metadata={
                    "owner_id": owner_id,
                    "max_attempts": max_attempts,
                    "delay_seconds": delay_seconds,
                    "available_at": available_at.isoformat(),
                },
                created_at=now.isoformat(),
                connection=connection,
            )

            created = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(created)

            if result is None:
                raise RuntimeError(
                    "Enqueued queue record could not be loaded."
                )

            return result

        except sqlite3.IntegrityError as exc:
            connection.rollback()

            raise ValueError(
                f"Task is already queued: {task_id}"
            ) from exc

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any] | None:
        worker_id = self._validate_text(
            worker_id,
            "Worker ID",
        )

        if not isinstance(lease_seconds, int):
            raise TypeError(
                "Lease duration must be an integer."
            )

        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError(
                "Lease duration must be between 5 and "
                "3600 seconds."
            )

        now = self._now()
        now_text = now.isoformat()

        lease_expires_at = (
            now + timedelta(seconds=lease_seconds)
        ).isoformat()

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            exhausted_rows = connection.execute(
                f"""
                SELECT *
                FROM {QUEUE_TABLE}
                WHERE
                    status = 'claimed'
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= ?
                    AND attempts >= max_attempts
                ORDER BY created_at ASC
                """,
                (now_text,),
            ).fetchall()

            for exhausted in exhausted_rows:
                error = (
                    exhausted["last_error"]
                    or (
                        "Maximum attempts reached after "
                        "worker lease expiry."
                    )
                )

                connection.execute(
                    f"""
                    UPDATE {QUEUE_TABLE}
                    SET
                        status = 'failed',
                        last_error = ?,
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE
                        task_id = ?
                        AND status = 'claimed'
                    """,
                    (
                        error,
                        now_text,
                        exhausted["task_id"],
                    ),
                )

                self._audit.append(
                    task_id=exhausted["task_id"],
                    attempt=int(exhausted["attempts"]),
                    event_type="failed",
                    queue_status="failed",
                    worker_id=exhausted["worker_id"],
                    message=(
                        "Expired worker lease exhausted "
                        "the queue attempt cycle."
                    ),
                    error=error,
                    metadata={
                        "reason": "lease_expired",
                        "max_attempts": int(
                            exhausted["max_attempts"]
                        ),
                        "lease_expires_at": exhausted[
                            "lease_expires_at"
                        ],
                    },
                    created_at=now_text,
                    connection=connection,
                )

            row = connection.execute(
                f"""
                SELECT *
                FROM {QUEUE_TABLE}
                WHERE
                    (
                        status = 'queued'
                        AND available_at <= ?
                    )
                    OR
                    (
                        status = 'claimed'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                        AND attempts < max_attempts
                    )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (
                    now_text,
                    now_text,
                ),
            ).fetchone()

            if row is None:
                connection.commit()
                return None

            task_id = row["task_id"]
            previous_status = row["status"]
            previous_worker_id = row["worker_id"]

            connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = 'claimed',
                    attempts = attempts + 1,
                    worker_id = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    worker_id,
                    lease_expires_at,
                    now_text,
                    task_id,
                ),
            )

            claimed = self._select_task(
                connection,
                task_id,
            )

            if claimed is None:
                raise RuntimeError(
                    "Claimed queue record could not be loaded."
                )

            self._audit.append(
                task_id=task_id,
                attempt=int(claimed["attempts"]),
                event_type="claimed",
                queue_status="claimed",
                worker_id=worker_id,
                message="Task claimed by durable worker.",
                metadata={
                    "lease_seconds": lease_seconds,
                    "lease_expires_at": lease_expires_at,
                    "previous_status": previous_status,
                    "previous_worker_id": previous_worker_id,
                    "recovered_expired_lease": (
                        previous_status == "claimed"
                    ),
                },
                created_at=now_text,
                connection=connection,
            )

            connection.commit()

            return self._row_to_dict(claimed)

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def complete(
        self,
        task_id: str,
        *,
        worker_id: str,
    ) -> dict[str, Any]:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )
        worker_id = self._validate_text(
            worker_id,
            "Worker ID",
        )

        now = self._now().isoformat()
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            current = self._select_task(
                connection,
                task_id,
            )

            if current is None:
                raise KeyError(
                    f"Queued task was not found: {task_id}"
                )

            cursor = connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = 'completed',
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE
                    task_id = ?
                    AND status = 'claimed'
                    AND worker_id = ?
                """,
                (
                    now,
                    task_id,
                    worker_id,
                ),
            )

            if cursor.rowcount == 0:
                raise PermissionError(
                    "The task is not claimed by this worker."
                )

            self._audit.append(
                task_id=task_id,
                attempt=int(current["attempts"]),
                event_type="completed",
                queue_status="completed",
                worker_id=worker_id,
                message="Durable queue delivery completed.",
                created_at=now,
                connection=connection,
            )

            updated = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(updated)

            if result is None:
                raise RuntimeError(
                    "Completed queue record could not be loaded."
                )

            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def fail(
        self,
        task_id: str,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 0,
    ) -> dict[str, Any]:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )
        worker_id = self._validate_text(
            worker_id,
            "Worker ID",
        )
        error = self._validate_text(
            error,
            "Queue error",
        )

        self._validate_delay(
            retry_delay_seconds
        )

        now = self._now()
        now_text = now.isoformat()
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            row = self._select_task(
                connection,
                task_id,
            )

            if row is None:
                raise KeyError(
                    f"Queued task was not found: {task_id}"
                )

            if (
                row["status"] != "claimed"
                or row["worker_id"] != worker_id
            ):
                raise PermissionError(
                    "The task is not claimed by this worker."
                )

            should_retry = (
                row["attempts"] < row["max_attempts"]
            )

            if should_retry:
                status = "queued"
                event_type = "retry_scheduled"
                message = (
                    "Queue delivery failed; another "
                    "automatic attempt was scheduled."
                )

                available_at = (
                    now
                    + timedelta(
                        seconds=retry_delay_seconds
                    )
                ).isoformat()

            else:
                status = "failed"
                event_type = "failed"
                message = (
                    "Queue delivery failed and the "
                    "attempt cycle was exhausted."
                )
                available_at = row["available_at"]

            connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = ?,
                    available_at = ?,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    available_at,
                    error,
                    now_text,
                    task_id,
                ),
            )

            self._audit.append(
                task_id=task_id,
                attempt=int(row["attempts"]),
                event_type=event_type,
                queue_status=status,
                worker_id=worker_id,
                message=message,
                error=error,
                metadata={
                    "retry_delay_seconds": (
                        retry_delay_seconds
                    ),
                    "max_attempts": int(
                        row["max_attempts"]
                    ),
                    "available_at": available_at,
                },
                created_at=now_text,
                connection=connection,
            )

            updated = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(updated)

            if result is None:
                raise RuntimeError(
                    "Failed queue record could not be loaded."
                )

            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def retry_failed(
        self,
        task_id: str,
        *,
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> dict[str, Any]:
        """
        Return a failed queue job to the executable queue.

        Only queue records whose current status is failed can be
        retried. The attempt counter is reset for a new retry cycle,
        while last_error remains available for diagnostics until the
        job succeeds or fails again.
        """

        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        self._validate_max_attempts(
            max_attempts
        )

        self._validate_delay(
            delay_seconds
        )

        now = self._now()
        now_text = now.isoformat()

        available_at = (
            now
            + timedelta(
                seconds=delay_seconds
            )
        ).isoformat()

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            row = self._select_task(
                connection,
                task_id,
            )

            if row is None:
                raise KeyError(
                    "Queued task was not found: "
                    f"{task_id}"
                )

            if row["status"] != "failed":
                raise ValueError(
                    "Only failed queue jobs can be "
                    "retried. Current status: "
                    f"{row['status']}."
                )

            cursor = connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = 'queued',
                    attempts = 0,
                    max_attempts = ?,
                    available_at = ?,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE
                    task_id = ?
                    AND status = 'failed'
                """,
                (
                    max_attempts,
                    available_at,
                    now_text,
                    task_id,
                ),
            )

            if cursor.rowcount == 0:
                raise RuntimeError(
                    "Failed queue job changed before "
                    "it could be retried."
                )

            self._audit.append(
                task_id=task_id,
                attempt=0,
                event_type="manually_retried",
                queue_status="queued",
                message=(
                    "Failed queue job started a new "
                    "manual retry cycle."
                ),
                error=row["last_error"],
                metadata={
                    "previous_attempts": int(
                        row["attempts"]
                    ),
                    "previous_max_attempts": int(
                        row["max_attempts"]
                    ),
                    "new_max_attempts": max_attempts,
                    "delay_seconds": delay_seconds,
                    "available_at": available_at,
                },
                created_at=now_text,
                connection=connection,
            )

            updated = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(
                updated
            )

            if result is None:
                raise RuntimeError(
                    "Retried queue record could "
                    "not be loaded."
                )

            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def cancel_queued(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """
        Cancel a task only while it is still queued.

        This operation is atomic. It refuses cancellation after a
        worker has claimed the task, preventing cancellation races
        with command execution.
        """

        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        now = self._now().isoformat()
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            row = self._select_task(
                connection,
                task_id,
            )

            if row is None:
                raise KeyError(
                    f"Queued task was not found: {task_id}"
                )

            cursor = connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = 'cancelled',
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE
                    task_id = ?
                    AND status = 'queued'
                """,
                (
                    now,
                    task_id,
                ),
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Task cannot be safely cancelled "
                    "from queue status "
                    f"{row['status']}."
                )

            self._audit.append(
                task_id=task_id,
                attempt=int(row["attempts"]),
                event_type="cancelled",
                queue_status="cancelled",
                message=(
                    "Queued task cancelled before "
                    "worker execution."
                ),
                metadata={
                    "previous_status": row["status"],
                    "cancellation_mode": "safe_queued",
                },
                created_at=now,
                connection=connection,
            )

            updated = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(updated)

            if result is None:
                raise RuntimeError(
                    "Cancelled queue record could not be loaded."
                )

            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def cancel(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """Cancel a queued or claimed task for internal reconciliation."""

        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        now = self._now().isoformat()
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            row = self._select_task(
                connection,
                task_id,
            )

            if row is None:
                raise KeyError(
                    f"Queued task was not found: {task_id}"
                )

            cursor = connection.execute(
                f"""
                UPDATE {QUEUE_TABLE}
                SET
                    status = 'cancelled',
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE
                    task_id = ?
                    AND status IN ('queued', 'claimed')
                """,
                (
                    now,
                    task_id,
                ),
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Task cannot be cancelled from queue "
                    f"status {row['status']}."
                )

            self._audit.append(
                task_id=task_id,
                attempt=int(row["attempts"]),
                event_type="cancelled",
                queue_status="cancelled",
                worker_id=row["worker_id"],
                message=(
                    "Queue job cancelled by an internal "
                    "runtime operation."
                ),
                metadata={
                    "previous_status": row["status"],
                    "cancellation_mode": "internal",
                },
                created_at=now,
                connection=connection,
            )

            updated = self._select_task(
                connection,
                task_id,
            )

            connection.commit()

            result = self._row_to_dict(updated)

            if result is None:
                raise RuntimeError(
                    "Cancelled queue record could not be loaded."
                )

            return result

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def get(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )

        with self._connect() as connection:
            row = self._select_task(
                connection,
                task_id,
            )

        return self._row_to_dict(row)

    def require(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        record = self.get(task_id)

        if record is None:
            raise KeyError(
                f"Queued task was not found: {task_id}"
            )

        return record

    def list(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._validate_limit(limit)

        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            status = self._validate_status(status)
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

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {QUEUE_TABLE}
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    def clear(self) -> None:
        """
        Clear queue records only.

        Attempt-audit rows are append-only and intentionally preserved.
        """

        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM {QUEUE_TABLE}"
            )

    def _now(self) -> datetime:
        current = self._clock()

        if not isinstance(current, datetime):
            raise TypeError(
                "Queue clock must return datetime."
            )

        if current.tzinfo is None:
            current = current.replace(
                tzinfo=timezone.utc
            )

        return current.astimezone(timezone.utc)

    @staticmethod
    def _select_task(
        connection: sqlite3.Connection,
        task_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            f"""
            SELECT *
            FROM {QUEUE_TABLE}
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    @staticmethod
    def _row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "task_id": row["task_id"],
            "owner_id": row["owner_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "available_at": row["available_at"],
            "lease_expires_at": row[
                "lease_expires_at"
            ],
            "worker_id": row["worker_id"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
    def _validate_status(status: str) -> str:
        status = SQLiteTaskQueueStore._validate_text(
            status,
            "Queue status",
        )

        if status not in QUEUE_STATUSES:
            raise ValueError(
                f"Unsupported queue status: {status}"
            )

        return status

    @staticmethod
    def _validate_max_attempts(
        max_attempts: int,
    ) -> None:
        if not isinstance(max_attempts, int):
            raise TypeError(
                "Maximum attempts must be an integer."
            )

        if max_attempts < 1 or max_attempts > 10:
            raise ValueError(
                "Maximum attempts must be between 1 and 10."
            )

    @staticmethod
    def _validate_delay(
        delay_seconds: int,
    ) -> None:
        if not isinstance(delay_seconds, int):
            raise TypeError(
                "Delay must be an integer."
            )

        if delay_seconds < 0 or delay_seconds > 86400:
            raise ValueError(
                "Delay must be between 0 and 86400 seconds."
            )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int):
            raise TypeError(
                "Limit must be an integer."
            )

        if limit < 1 or limit > 1000:
            raise ValueError(
                "Limit must be between 1 and 1000."
            )


task_queue_store = SQLiteTaskQueueStore()


__all__ = [
    "QUEUE_STATUSES",
    "QUEUE_TABLE",
    "SQLiteTaskQueueStore",
    "task_queue_store",
]