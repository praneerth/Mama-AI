"""Versioned SQLite schema migrations for Mama AI.

The migration manager is intentionally dependency-free and uses an
exclusive SQLite transaction so concurrent startup processes cannot apply
the same migration twice. Applied migration checksums are validated on
every run; edited historical migrations fail closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.config import settings
from app.database import database


SCHEMA_MIGRATION_TABLE = "schema_migrations"
MIGRATION_ROLLBACK_CONFIRMATION = "ROLLBACK_LAST_MAMA_AI_MIGRATION"


class MigrationError(RuntimeError):
    """Base class for migration failures."""


class MigrationChecksumError(MigrationError):
    """Raised when an applied migration no longer matches its checksum."""


class MigrationVersionError(MigrationError):
    """Raised when the database is newer than the running application."""


class MigrationRollbackError(MigrationError):
    """Raised when a migration cannot be safely rolled back."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    rollback_statements: tuple[str, ...] = ()

    @property
    def checksum(self) -> str:
        payload = {
            "version": self.version,
            "name": self.name,
            "statements": list(self.statements),
            "rollback_statements": list(self.rollback_statements),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


DEFAULT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="database_backup_catalog",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS database_backup_catalog (
                backup_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                integrity_status TEXT NOT NULL,
                verified_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'deleted', 'restored')),
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_database_backup_catalog_created
            ON database_backup_catalog(created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_database_backup_catalog_status
            ON database_backup_catalog(status, created_at DESC)
            """,
        ),
    ),
    Migration(
        version=2,
        name="database_recovery_state",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS database_recovery_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            INSERT OR IGNORE INTO database_recovery_state(
                state_key,
                state_value
            ) VALUES ('recovery_schema_version', '1')
            """,
        ),
        rollback_statements=(
            "DROP TABLE IF EXISTS database_recovery_state",
        ),
    ),
)


class MigrationManager:
    """Apply, validate, inspect, and selectively roll back migrations."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        migrations: Sequence[Migration] = DEFAULT_MIGRATIONS,
    ) -> None:
        self._database_path = (
            str(database_path)
            if database_path is not None
            else None
        )
        self.migrations = tuple(sorted(migrations, key=lambda item: item.version))
        self._validate_definitions()
        self._lock = threading.RLock()

    @property
    def database_path(self) -> str:
        return self._database_path or str(database.DATABASE_PATH)

    def _validate_definitions(self) -> None:
        versions = [item.version for item in self.migrations]
        if any(version < 1 for version in versions):
            raise ValueError("Migration versions must be positive integers.")
        if len(set(versions)) != len(versions):
            raise ValueError("Migration versions must be unique.")
        if versions and versions != list(range(versions[0], versions[-1] + 1)):
            raise ValueError("Migration versions must be contiguous.")
        for migration in self.migrations:
            if not migration.name.strip():
                raise ValueError("Migration names cannot be empty.")
            if not migration.statements:
                raise ValueError("Migrations must contain at least one statement.")

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path),
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _ensure_history_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATION_TABLE} (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                execution_ms REAL NOT NULL
            )
            """
        )

    @staticmethod
    def _applied_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            f"""
            SELECT version, name, checksum, applied_at, execution_ms
            FROM {SCHEMA_MIGRATION_TABLE}
            ORDER BY version
            """
        ).fetchall()

    def _validate_applied(self, rows: Iterable[sqlite3.Row]) -> None:
        known = {item.version: item for item in self.migrations}
        for row in rows:
            version = int(row["version"])
            migration = known.get(version)
            if migration is None:
                raise MigrationVersionError(
                    f"Database migration version {version} is newer than this application."
                )
            if row["name"] != migration.name or row["checksum"] != migration.checksum:
                raise MigrationChecksumError(
                    f"Applied migration {version} does not match the application checksum."
                )

    def migrate(self) -> dict[str, object]:
        if not bool(getattr(settings, "DATABASE_MIGRATIONS_ENABLED", True)):
            return {
                "enabled": False,
                "applied": [],
                "current_version": None,
                "latest_version": self.migrations[-1].version if self.migrations else 0,
            }
        with self._lock:
            connection = self._connect()
            try:
                self._ensure_history_table(connection)
                connection.commit()
                rows = self._applied_rows(connection)
                self._validate_applied(rows)
                applied_versions = {int(row["version"]) for row in rows}
                applied_now: list[dict[str, object]] = []
                for migration in self.migrations:
                    if migration.version in applied_versions:
                        continue
                    started = time.perf_counter()
                    try:
                        connection.execute("BEGIN IMMEDIATE")
                        for statement in migration.statements:
                            connection.execute(statement)
                        elapsed_ms = (time.perf_counter() - started) * 1000.0
                        connection.execute(
                            f"""
                            INSERT INTO {SCHEMA_MIGRATION_TABLE}(
                                version, name, checksum, execution_ms
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                migration.version,
                                migration.name,
                                migration.checksum,
                                elapsed_ms,
                            ),
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
                    applied_now.append(
                        {
                            "version": migration.version,
                            "name": migration.name,
                            "checksum": migration.checksum,
                            "execution_ms": round(elapsed_ms, 3),
                        }
                    )
                current = self._applied_rows(connection)
                self._validate_applied(current)
                current_version = int(current[-1]["version"]) if current else 0
                return {
                    "enabled": True,
                    "applied": applied_now,
                    "current_version": current_version,
                    "latest_version": self.migrations[-1].version if self.migrations else 0,
                }
            finally:
                connection.close()

    def status(self) -> dict[str, object]:
        with self._lock:
            connection = self._connect()
            try:
                self._ensure_history_table(connection)
                connection.commit()
                rows = self._applied_rows(connection)
                self._validate_applied(rows)
                applied_versions = {int(row["version"]) for row in rows}
                pending = [
                    {"version": item.version, "name": item.name}
                    for item in self.migrations
                    if item.version not in applied_versions
                ]
                return {
                    "enabled": bool(getattr(settings, "DATABASE_MIGRATIONS_ENABLED", True)),
                    "current_version": max(applied_versions, default=0),
                    "latest_version": self.migrations[-1].version if self.migrations else 0,
                    "pending": pending,
                    "applied": [
                        {
                            "version": int(row["version"]),
                            "name": row["name"],
                            "checksum": row["checksum"],
                            "applied_at": row["applied_at"],
                            "execution_ms": float(row["execution_ms"]),
                        }
                        for row in rows
                    ],
                }
            finally:
                connection.close()

    def rollback_last(self, *, confirmation: str) -> dict[str, object]:
        if confirmation != MIGRATION_ROLLBACK_CONFIRMATION:
            raise MigrationRollbackError("Explicit migration rollback confirmation is required.")
        with self._lock:
            connection = self._connect()
            try:
                self._ensure_history_table(connection)
                connection.commit()
                rows = self._applied_rows(connection)
                self._validate_applied(rows)
                if not rows:
                    raise MigrationRollbackError("No applied migration is available to roll back.")
                version = int(rows[-1]["version"])
                migration = next(item for item in self.migrations if item.version == version)
                if not migration.rollback_statements:
                    raise MigrationRollbackError(
                        f"Migration {version} is intentionally irreversible."
                    )
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in migration.rollback_statements:
                        connection.execute(statement)
                    connection.execute(
                        f"DELETE FROM {SCHEMA_MIGRATION_TABLE} WHERE version = ?",
                        (version,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                return {"rolled_back": True, "version": version, "name": migration.name}
            finally:
                connection.close()


migration_manager = MigrationManager()


def migrate() -> dict[str, object]:
    """Compatibility entry point used by existing scripts."""
    return migration_manager.migrate()


if __name__ == "__main__":
    print(json.dumps(migrate(), indent=2, sort_keys=True))


__all__ = [
    "DEFAULT_MIGRATIONS",
    "MIGRATION_ROLLBACK_CONFIRMATION",
    "Migration",
    "MigrationChecksumError",
    "MigrationError",
    "MigrationManager",
    "MigrationRollbackError",
    "MigrationVersionError",
    "SCHEMA_MIGRATION_TABLE",
    "migrate",
    "migration_manager",
]
