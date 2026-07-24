"""SQLite backup, verification, retention, integrity, and restore support."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from typing import Any, Iterator
from uuid import uuid4

from app.config import settings
from app.database import database
from app.database.migrations import migration_manager


BACKUP_CATALOG_TABLE = "database_backup_catalog"
RESTORE_CONFIRMATION = "RESTORE_MAMA_AI_DATABASE"
_BACKUP_NAME_PATTERN = re.compile(r"^mama_ai_[0-9]{8}T[0-9]{12}Z_[a-f0-9]{8}\.db$")


class DatabaseRecoveryError(RuntimeError):
    pass


class BackupNotFoundError(DatabaseRecoveryError):
    pass


class BackupIntegrityError(DatabaseRecoveryError):
    pass


class RecoveryBusyError(DatabaseRecoveryError):
    pass


class RestoreConfirmationError(DatabaseRecoveryError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_integrity_check(
    database_path: str | Path,
    *,
    mode: str = "quick",
) -> dict[str, Any]:
    path = Path(database_path)
    if not path.exists():
        return {
            "ok": False,
            "mode": mode,
            "messages": ["Database file does not exist."],
        }
    pragma = "integrity_check" if mode == "full" else "quick_check"
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=30,
        )
        try:
            rows = connection.execute(f"PRAGMA {pragma}").fetchall()
        finally:
            connection.close()
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode,
            "messages": [f"{type(exc).__name__}: database could not be checked."],
        }
    messages = [str(row[0]) for row in rows]
    return {
        "ok": messages == ["ok"],
        "mode": mode,
        "messages": messages[:50],
    }


class BackupManager:
    def __init__(
        self,
        database_path: str | Path | None = None,
        backup_directory: str | Path | None = None,
        *,
        retention_count: int | None = None,
        integrity_mode: str | None = None,
    ) -> None:
        self._database_path = str(database_path) if database_path is not None else None
        self.backup_directory = Path(
            backup_directory
            if backup_directory is not None
            else settings.DATABASE_BACKUP_DIR
        )
        self.retention_count = int(
            retention_count
            if retention_count is not None
            else settings.DATABASE_BACKUP_RETENTION_COUNT
        )
        self.integrity_mode = (
            integrity_mode
            if integrity_mode is not None
            else settings.DATABASE_INTEGRITY_CHECK_MODE
        )
        if self.retention_count < 1:
            raise ValueError("Backup retention count must be at least 1.")
        if self.integrity_mode not in {"quick", "full"}:
            raise ValueError("Integrity mode must be quick or full.")
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()

    @property
    def database_path(self) -> Path:
        return Path(self._database_path or str(database.DATABASE_PATH))

    @property
    def _lock_path(self) -> Path:
        return self.backup_directory / ".mama_ai_database_recovery.lock"

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        with self._thread_lock:
            fd: int | None = None
            acquired = False
            try:
                try:
                    fd = os.open(
                        str(self._lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    )
                except FileExistsError as exc:
                    try:
                        age = utc_now().timestamp() - self._lock_path.stat().st_mtime
                    except OSError:
                        age = 0
                    if age > 3600:
                        self._lock_path.unlink(missing_ok=True)
                        fd = os.open(
                            str(self._lock_path),
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        )
                    else:
                        raise RecoveryBusyError(
                            "Another database recovery operation is already running."
                        ) from exc
                os.write(fd, f"pid={os.getpid()}\ncreated_at={_iso()}\n".encode("utf-8"))
                os.close(fd)
                fd = None
                acquired = True
                yield
            finally:
                if fd is not None:
                    os.close(fd)
                if acquired:
                    self._lock_path.unlink(missing_ok=True)

    def _connect_catalog(self) -> sqlite3.Connection:
        migration_manager_for_path = type(migration_manager)(self.database_path)
        migration_manager_for_path.migrate()
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _safe_backup_path(self, filename: str) -> Path:
        name = Path(str(filename)).name
        if name != filename or not _BACKUP_NAME_PATTERN.fullmatch(name):
            raise BackupNotFoundError("Backup name is invalid.")
        candidate = (self.backup_directory / name).resolve()
        if candidate.parent != self.backup_directory.resolve():
            raise BackupNotFoundError("Backup name is invalid.")
        if not candidate.exists():
            raise BackupNotFoundError("Backup does not exist.")
        return candidate

    @staticmethod
    def _metadata_path(backup_path: Path) -> Path:
        return backup_path.with_suffix(backup_path.suffix + ".json")

    def _write_metadata(self, backup_path: Path, metadata: dict[str, Any]) -> None:
        metadata_path = self._metadata_path(backup_path)
        temporary = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, metadata_path)

    def _read_metadata(self, backup_path: Path) -> dict[str, Any]:
        metadata_path = self._metadata_path(backup_path)
        if not metadata_path.exists():
            raise BackupIntegrityError("Backup metadata is missing.")
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupIntegrityError("Backup metadata is invalid.") from exc
        if not isinstance(loaded, dict):
            raise BackupIntegrityError("Backup metadata is invalid.")
        return loaded

    def _record_catalog(self, metadata: dict[str, Any], *, status: str = "active") -> None:
        try:
            connection = self._connect_catalog()
            try:
                with connection:
                    connection.execute(
                        f"""
                        INSERT INTO {BACKUP_CATALOG_TABLE}(
                            backup_id, filename, created_at, reason,
                            size_bytes, sha256, integrity_status,
                            verified_at, status, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(filename) DO UPDATE SET
                            reason = excluded.reason,
                            size_bytes = excluded.size_bytes,
                            sha256 = excluded.sha256,
                            integrity_status = excluded.integrity_status,
                            verified_at = excluded.verified_at,
                            status = excluded.status,
                            metadata_json = excluded.metadata_json
                        """,
                        (
                            metadata["backup_id"],
                            metadata["filename"],
                            metadata["created_at"],
                            metadata["reason"],
                            metadata["size_bytes"],
                            metadata["sha256"],
                            metadata["integrity_status"],
                            metadata.get("verified_at"),
                            status,
                            json.dumps(metadata.get("metadata", {}), sort_keys=True),
                        ),
                    )
            finally:
                connection.close()
        except Exception:
            # The backup file remains usable even if catalog persistence fails.
            return

    def create_backup(
        self,
        *,
        reason: str = "manual",
        metadata: dict[str, Any] | None = None,
        apply_retention: bool = True,
    ) -> dict[str, Any]:
        with self._operation_lock():
            result = self._create_backup_unlocked(reason=reason, metadata=metadata)
            if apply_retention:
                self._prune_unlocked(self.retention_count)
            return result

    def _create_backup_unlocked(
        self,
        *,
        reason: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source = self.database_path
        if not source.exists():
            raise DatabaseRecoveryError("Runtime database does not exist.")
        source_integrity = run_integrity_check(source, mode=self.integrity_mode)
        if not source_integrity["ok"]:
            raise BackupIntegrityError("Runtime database integrity check failed.")
        normalized_reason = str(reason).strip()[:100] or "manual"
        created = utc_now()
        backup_id = uuid4().hex
        filename = f"mama_ai_{created.strftime('%Y%m%dT%H%M%S%fZ')}_{backup_id[:8]}.db"
        destination = self.backup_directory / filename
        partial = destination.with_suffix(destination.suffix + ".partial")
        source_connection = sqlite3.connect(
            f"file:{source.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=30,
        )
        target_connection = sqlite3.connect(str(partial), timeout=30)
        try:
            source_connection.backup(target_connection)
            target_connection.commit()
        finally:
            target_connection.close()
            source_connection.close()
        os.replace(partial, destination)
        backup_integrity = run_integrity_check(destination, mode=self.integrity_mode)
        if not backup_integrity["ok"]:
            destination.unlink(missing_ok=True)
            raise BackupIntegrityError("Created backup failed integrity verification.")
        result = {
            "backup_id": backup_id,
            "filename": filename,
            "created_at": _iso(created),
            "reason": normalized_reason,
            "size_bytes": destination.stat().st_size,
            "sha256": _sha256_file(destination),
            "integrity_status": "ok",
            "verified_at": _iso(),
            "metadata": dict(metadata or {}),
        }
        self._write_metadata(destination, result)
        self._record_catalog(result)
        return dict(result)

    def list_backups(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000.")
        results: list[dict[str, Any]] = []
        for path in self.backup_directory.glob("mama_ai_*.db"):
            try:
                metadata = self._read_metadata(path)
                results.append(
                    {
                        "backup_id": metadata.get("backup_id"),
                        "filename": path.name,
                        "created_at": metadata.get("created_at"),
                        "reason": metadata.get("reason"),
                        "size_bytes": path.stat().st_size,
                        "sha256": metadata.get("sha256"),
                        "integrity_status": metadata.get("integrity_status", "unknown"),
                        "verified_at": metadata.get("verified_at"),
                    }
                )
            except (OSError, DatabaseRecoveryError):
                results.append(
                    {
                        "backup_id": None,
                        "filename": path.name,
                        "created_at": None,
                        "reason": None,
                        "size_bytes": path.stat().st_size if path.exists() else 0,
                        "sha256": None,
                        "integrity_status": "metadata_invalid",
                        "verified_at": None,
                    }
                )
        results.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return results[:limit]

    def verify_backup(self, filename: str) -> dict[str, Any]:
        with self._operation_lock():
            path = self._safe_backup_path(filename)
            metadata = self._read_metadata(path)
            expected = str(metadata.get("sha256", ""))
            actual = _sha256_file(path)
            if not expected or not hmac.compare_digest(expected, actual):
                raise BackupIntegrityError("Backup checksum verification failed.")
            integrity = run_integrity_check(path, mode=self.integrity_mode)
            if not integrity["ok"]:
                raise BackupIntegrityError("Backup SQLite integrity verification failed.")
            metadata["size_bytes"] = path.stat().st_size
            metadata["integrity_status"] = "ok"
            metadata["verified_at"] = _iso()
            self._write_metadata(path, metadata)
            self._record_catalog(metadata)
            return {
                "filename": path.name,
                "size_bytes": metadata["size_bytes"],
                "sha256": actual,
                "integrity_status": "ok",
                "verified_at": metadata["verified_at"],
            }

    def prune_backups(self, *, keep: int | None = None) -> dict[str, Any]:
        with self._operation_lock():
            return self._prune_unlocked(self.retention_count if keep is None else keep)

    def _prune_unlocked(self, keep: int) -> dict[str, Any]:
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
            raise ValueError("At least one backup must be retained.")
        backups = self.list_backups(limit=1000)
        removed: list[str] = []
        for item in backups[keep:]:
            filename = item["filename"]
            try:
                path = self._safe_backup_path(filename)
            except BackupNotFoundError:
                continue
            self._metadata_path(path).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            removed.append(filename)
            try:
                connection = self._connect_catalog()
                try:
                    with connection:
                        connection.execute(
                            f"UPDATE {BACKUP_CATALOG_TABLE} SET status = 'deleted' WHERE filename = ?",
                            (filename,),
                        )
                finally:
                    connection.close()
            except Exception:
                pass
        return {"kept": min(len(backups), keep), "removed": removed}

    def restore_backup(self, filename: str, *, confirmation: str) -> dict[str, Any]:
        if confirmation != RESTORE_CONFIRMATION:
            raise RestoreConfirmationError("Explicit database restore confirmation is required.")
        with self._operation_lock():
            backup_path = self._safe_backup_path(filename)
            metadata = self._read_metadata(backup_path)
            expected = str(metadata.get("sha256", ""))
            if not expected or not hmac.compare_digest(expected, _sha256_file(backup_path)):
                raise BackupIntegrityError("Backup checksum verification failed.")
            if not run_integrity_check(backup_path, mode=self.integrity_mode)["ok"]:
                raise BackupIntegrityError("Backup SQLite integrity verification failed.")
            source = self.database_path
            pre_restore = None
            if source.exists():
                pre_restore = self._create_backup_unlocked(
                    reason="pre_restore_safety",
                    metadata={"restore_source": backup_path.name},
                )
                try:
                    connection = sqlite3.connect(str(source), timeout=5)
                    try:
                        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        connection.close()
                except sqlite3.Error:
                    pass
            source.parent.mkdir(parents=True, exist_ok=True)
            temporary = source.with_suffix(source.suffix + ".restore.tmp")
            previous = source.with_suffix(source.suffix + ".restore.previous")
            copy2(backup_path, temporary)
            if not run_integrity_check(temporary, mode=self.integrity_mode)["ok"]:
                temporary.unlink(missing_ok=True)
                raise BackupIntegrityError("Temporary restore copy failed integrity verification.")
            previous.unlink(missing_ok=True)
            try:
                if source.exists():
                    os.replace(source, previous)
                os.replace(temporary, source)
                source.with_name(source.name + "-wal").unlink(missing_ok=True)
                source.with_name(source.name + "-shm").unlink(missing_ok=True)
                type(migration_manager)(source).migrate()
                final_integrity = run_integrity_check(source, mode=self.integrity_mode)
                if not final_integrity["ok"]:
                    raise BackupIntegrityError("Restored database failed integrity verification.")
                previous.unlink(missing_ok=True)
            except Exception:
                temporary.unlink(missing_ok=True)
                if previous.exists():
                    source.unlink(missing_ok=True)
                    os.replace(previous, source)
                raise
            restored_record = dict(metadata)
            restored_record["verified_at"] = _iso()
            self._record_catalog(restored_record, status="restored")
            return {
                "restored": True,
                "filename": backup_path.name,
                "integrity_status": "ok",
                "pre_restore_backup": pre_restore["filename"] if pre_restore else None,
            }

    def status(self) -> dict[str, Any]:
        integrity = run_integrity_check(self.database_path, mode=self.integrity_mode)
        backups = self.list_backups(limit=1000)
        latest = backups[0] if backups else None
        return {
            "database_available": self.database_path.exists(),
            "integrity": integrity,
            "backup_enabled": bool(settings.DATABASE_BACKUP_ENABLED),
            "backup_count": len(backups),
            "latest_backup": latest,
            "retention_count": self.retention_count,
        }


backup_manager = BackupManager()


__all__ = [
    "BACKUP_CATALOG_TABLE",
    "BackupIntegrityError",
    "BackupManager",
    "BackupNotFoundError",
    "DatabaseRecoveryError",
    "RESTORE_CONFIRMATION",
    "RecoveryBusyError",
    "RestoreConfirmationError",
    "backup_manager",
    "run_integrity_check",
]
