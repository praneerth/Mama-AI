"""Persistent trusted-device and account API-key storage for Mama AI."""

from __future__ import annotations

import hmac
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.device_security import (
    fingerprint_api_key,
    fingerprint_device_reference,
    normalize_api_key_name,
    normalize_api_key_scopes,
    normalize_device_name,
    normalize_ip_address,
    normalize_user_agent,
    parse_api_key,
)
from app.database.auth_db import SESSION_TABLE, USER_TABLE
from app.database.database import DATABASE_PATH


DEVICE_TABLE = "account_trusted_devices"
SESSION_DEVICE_TABLE = "authentication_session_devices"
API_KEY_TABLE = "account_api_keys"

DEVICE_STATUSES = frozenset({"untrusted", "trusted", "revoked"})
API_KEY_STATUSES = frozenset({"active", "revoked", "expired"})


class SQLiteDeviceSecurityStore:
    """SQLite storage for user devices, device sessions, and API keys."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        *,
        clock: Callable[[], datetime] | None = None,
        initialize: bool = True,
    ) -> None:
        self.database_path = str(database_path)
        self._clock = clock if clock is not None else lambda: datetime.now(
            timezone.utc
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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        database_file = Path(self.database_path)
        database_file.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {DEVICE_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    client_ref_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('untrusted', 'trusted', 'revoked')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    trusted_at TEXT,
                    revoked_at TEXT,
                    last_ip TEXT,
                    last_user_agent TEXT,
                    last_session_id TEXT,
                    UNIQUE(user_id, client_ref_fingerprint),
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_account_devices_user_status
                ON {DEVICE_TABLE}(user_id, status, last_seen_at DESC);

                CREATE TABLE IF NOT EXISTS {SESSION_DEVICE_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_ip TEXT,
                    last_user_agent TEXT,
                    FOREIGN KEY(session_id)
                        REFERENCES {SESSION_TABLE}(session_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(device_id)
                        REFERENCES {DEVICE_TABLE}(device_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_session_devices_user_device
                ON {SESSION_DEVICE_TABLE}(user_id, device_id, last_seen_at DESC);

                CREATE TABLE IF NOT EXISTS {API_KEY_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    key_fingerprint TEXT NOT NULL UNIQUE,
                    key_reference TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'revoked', 'expired')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    last_used_at TEXT,
                    last_ip TEXT,
                    revoked_at TEXT,
                    rotated_from_key_id TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_account_api_keys_user_status
                ON {API_KEY_TABLE}(user_id, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_account_api_keys_expiry
                ON {API_KEY_TABLE}(expires_at);
                """
            )

    def register_session_device(
        self,
        *,
        user_id: str,
        session_id: str,
        device_name: str | None,
        client_ref: str | None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        session_id = self._validate_text(session_id, "Session ID", 128)
        name = normalize_device_name(device_name)
        stable_ref = client_ref.strip() if isinstance(client_ref, str) else ""
        if not stable_ref:
            stable_ref = "session:" + session_id
        ref_fingerprint = fingerprint_device_reference(stable_ref)
        try:
            normalized_ip = normalize_ip_address(client_ip)
        except (TypeError, ValueError):
            normalized_ip = None
        normalized_agent = normalize_user_agent(user_agent)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            session = connection.execute(
                f"""
                SELECT user_id, status
                FROM {SESSION_TABLE}
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            if (
                session is None
                or session["user_id"] != user_id
                or session["status"] != "active"
            ):
                raise KeyError("Active authentication session was not found.")

            row = connection.execute(
                f"""
                SELECT *
                FROM {DEVICE_TABLE}
                WHERE user_id = ? AND client_ref_fingerprint = ?
                """,
                (user_id, ref_fingerprint),
            ).fetchone()

            if row is None:
                device_id = uuid4().hex
                connection.execute(
                    f"""
                    INSERT INTO {DEVICE_TABLE} (
                        device_id,
                        user_id,
                        device_name,
                        client_ref_fingerprint,
                        status,
                        created_at,
                        updated_at,
                        first_seen_at,
                        last_seen_at,
                        trusted_at,
                        revoked_at,
                        last_ip,
                        last_user_agent,
                        last_session_id
                    ) VALUES (?, ?, ?, ?, 'untrusted', ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        device_id,
                        user_id,
                        name,
                        ref_fingerprint,
                        now_text,
                        now_text,
                        now_text,
                        now_text,
                        normalized_ip,
                        normalized_agent,
                        session_id,
                    ),
                )
            else:
                device_id = row["device_id"]
                status = row["status"]
                if status == "revoked":
                    status = "untrusted"
                connection.execute(
                    f"""
                    UPDATE {DEVICE_TABLE}
                    SET
                        device_name = ?,
                        status = ?,
                        updated_at = ?,
                        last_seen_at = ?,
                        trusted_at = CASE WHEN ? = 'trusted' THEN trusted_at ELSE NULL END,
                        revoked_at = NULL,
                        last_ip = ?,
                        last_user_agent = ?,
                        last_session_id = ?
                    WHERE device_id = ? AND user_id = ?
                    """,
                    (
                        name,
                        status,
                        now_text,
                        now_text,
                        status,
                        normalized_ip,
                        normalized_agent,
                        session_id,
                        device_id,
                        user_id,
                    ),
                )

            connection.execute(
                f"""
                INSERT INTO {SESSION_DEVICE_TABLE} (
                    session_id,
                    user_id,
                    device_id,
                    linked_at,
                    last_seen_at,
                    last_ip,
                    last_user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    device_id = excluded.device_id,
                    last_seen_at = excluded.last_seen_at,
                    last_ip = excluded.last_ip,
                    last_user_agent = excluded.last_user_agent
                """,
                (
                    session_id,
                    user_id,
                    device_id,
                    now_text,
                    now_text,
                    normalized_ip,
                    normalized_agent,
                ),
            )

        device = self.get_device(user_id=user_id, device_id=device_id)
        if device is None:
            raise RuntimeError("Registered device could not be loaded.")
        return device

    def touch_session_device(
        self,
        *,
        session_id: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | None:
        session_id = self._validate_text(session_id, "Session ID", 128)
        try:
            normalized_ip = normalize_ip_address(client_ip)
        except (TypeError, ValueError):
            normalized_ip = None
        normalized_agent = normalize_user_agent(user_agent)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            row = connection.execute(
                f"SELECT user_id, device_id FROM {SESSION_DEVICE_TABLE} WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None

            connection.execute(
                f"""
                UPDATE {SESSION_DEVICE_TABLE}
                SET last_seen_at = ?, last_ip = ?, last_user_agent = ?
                WHERE session_id = ?
                """,
                (now_text, normalized_ip, normalized_agent, session_id),
            )
            connection.execute(
                f"""
                UPDATE {DEVICE_TABLE}
                SET
                    updated_at = ?,
                    last_seen_at = ?,
                    last_ip = ?,
                    last_user_agent = ?,
                    last_session_id = ?
                WHERE device_id = ? AND user_id = ?
                """,
                (
                    now_text,
                    now_text,
                    normalized_ip,
                    normalized_agent,
                    session_id,
                    row["device_id"],
                    row["user_id"],
                ),
            )

        return self.get_device(
            user_id=row["user_id"],
            device_id=row["device_id"],
        )

    def get_device(
        self,
        *,
        user_id: str,
        device_id: str,
    ) -> dict[str, Any] | None:
        user_id = self._validate_text(user_id, "User ID", 128)
        device_id = self._validate_text(device_id, "Device ID", 128)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {DEVICE_TABLE} WHERE user_id = ? AND device_id = ?",
                (user_id, device_id),
            ).fetchone()
        return self._device_row_to_dict(row)

    def list_devices(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        user_id = self._validate_text(user_id, "User ID", 128)
        limit = self._validate_limit(limit)
        conditions = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if status is not None:
            status = self._validate_device_status(status)
            conditions.append("status = ?")
            parameters.append(status)
        parameters.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM {DEVICE_TABLE}
                WHERE {' AND '.join(conditions)}
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        return [self._device_row_to_dict(row) for row in rows]

    def list_session_devices(
        self,
        *,
        user_id: str,
        limit: int = 1000,
    ) -> dict[str, dict[str, Any]]:
        user_id = self._validate_text(user_id, "User ID", 128)
        limit = self._validate_limit(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    sd.session_id,
                    sd.linked_at,
                    sd.last_seen_at AS session_device_last_seen_at,
                    sd.last_ip AS session_last_ip,
                    sd.last_user_agent AS session_last_user_agent,
                    d.device_id,
                    d.device_name,
                    d.status AS device_status,
                    d.trusted_at,
                    d.revoked_at AS device_revoked_at
                FROM {SESSION_DEVICE_TABLE} AS sd
                JOIN {DEVICE_TABLE} AS d ON d.device_id = sd.device_id
                WHERE sd.user_id = ?
                ORDER BY sd.last_seen_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return {
            row["session_id"]: {
                "device_id": row["device_id"],
                "device_name": row["device_name"],
                "status": row["device_status"],
                "trusted": row["device_status"] == "trusted",
                "linked_at": row["linked_at"],
                "last_seen_at": row["session_device_last_seen_at"],
                "last_ip": row["session_last_ip"],
                "last_user_agent": row["session_last_user_agent"],
                "trusted_at": row["trusted_at"],
                "revoked_at": row["device_revoked_at"],
            }
            for row in rows
        }

    def list_device_sessions(
        self,
        *,
        user_id: str,
        device_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        user_id = self._validate_text(user_id, "User ID", 128)
        device_id = self._validate_text(device_id, "Device ID", 128)
        limit = self._validate_limit(limit)
        if self.get_device(user_id=user_id, device_id=device_id) is None:
            raise KeyError("Device was not found.")
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    sd.session_id,
                    sd.user_id,
                    sd.device_id,
                    sd.linked_at,
                    sd.last_seen_at,
                    sd.last_ip,
                    sd.last_user_agent,
                    s.status,
                    s.created_at,
                    s.expires_at,
                    s.revoked_at
                FROM {SESSION_DEVICE_TABLE} AS sd
                JOIN {SESSION_TABLE} AS s ON s.session_id = sd.session_id
                WHERE sd.user_id = ? AND sd.device_id = ?
                ORDER BY sd.last_seen_at DESC
                LIMIT ?
                """,
                (user_id, device_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_device_trust(
        self,
        *,
        user_id: str,
        device_id: str,
        trusted: bool,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        device_id = self._validate_text(device_id, "Device ID", 128)
        if not isinstance(trusted, bool):
            raise TypeError("Trusted flag must be boolean.")
        now_text = self._now().isoformat()
        status = "trusted" if trusted else "untrusted"
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {DEVICE_TABLE}
                SET
                    status = ?,
                    updated_at = ?,
                    trusted_at = ?,
                    revoked_at = NULL
                WHERE user_id = ? AND device_id = ?
                """,
                (
                    status,
                    now_text,
                    now_text if trusted else None,
                    user_id,
                    device_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError("Device was not found.")
        device = self.get_device(user_id=user_id, device_id=device_id)
        if device is None:
            raise RuntimeError("Updated device could not be loaded.")
        return device

    def revoke_device(
        self,
        *,
        user_id: str,
        device_id: str,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        device_id = self._validate_text(device_id, "Device ID", 128)
        now_text = self._now().isoformat()
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT status FROM {DEVICE_TABLE} WHERE user_id = ? AND device_id = ?",
                (user_id, device_id),
            ).fetchone()
            if row is None:
                raise KeyError("Device was not found.")
            session_rows = connection.execute(
                f"""
                SELECT session_id FROM {SESSION_DEVICE_TABLE}
                WHERE user_id = ? AND device_id = ?
                """,
                (user_id, device_id),
            ).fetchall()
            session_ids = [item["session_id"] for item in session_rows]
            revoked_sessions = 0
            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)
                cursor = connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET status = 'revoked', updated_at = ?, revoked_at = ?
                    WHERE user_id = ? AND status = 'active'
                      AND session_id IN ({placeholders})
                    """,
                    (now_text, now_text, user_id, *session_ids),
                )
                revoked_sessions = int(cursor.rowcount)
            connection.execute(
                f"""
                UPDATE {DEVICE_TABLE}
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE user_id = ? AND device_id = ?
                """,
                (now_text, now_text, user_id, device_id),
            )
        device = self.get_device(user_id=user_id, device_id=device_id)
        if device is None:
            raise RuntimeError("Revoked device could not be loaded.")
        return {"device": device, "revoked_sessions": revoked_sessions}

    def create_api_key(
        self,
        *,
        user_id: str,
        key_id: str,
        raw_api_key: str,
        name: str,
        scopes: list[str] | tuple[str, ...],
        expires_in_seconds: int | None,
        max_active_keys: int,
        rotated_from_key_id: str | None = None,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        key_id = self._validate_text(key_id, "API key ID", 128)
        parsed_id, _ = parse_api_key(raw_api_key)
        if parsed_id != key_id:
            raise ValueError("API key identifier does not match its token.")
        name = normalize_api_key_name(name)
        normalized_scopes = normalize_api_key_scopes(scopes)
        max_active_keys = self._validate_max_active_keys(max_active_keys)
        expires_at = self._expiry_from_seconds(expires_in_seconds)
        now_text = self._now().isoformat()
        fingerprint = fingerprint_api_key(raw_api_key)
        key_reference = key_id[:12]
        if rotated_from_key_id is not None:
            rotated_from_key_id = self._validate_text(
                rotated_from_key_id, "Rotated API key ID", 128
            )

        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            user = connection.execute(
                f"SELECT status FROM {USER_TABLE} WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if user is None or user["status"] != "active":
                raise KeyError("Active user account was not found.")
            active_count = connection.execute(
                f"""
                SELECT COUNT(*) FROM {API_KEY_TABLE}
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            ).fetchone()[0]
            if int(active_count) >= max_active_keys:
                raise OverflowError("Maximum active API key limit reached.")
            connection.execute(
                f"""
                INSERT INTO {API_KEY_TABLE} (
                    key_id, user_id, name, key_fingerprint, key_reference,
                    scopes_json, status, created_at, updated_at, expires_at,
                    last_used_at, last_ip, revoked_at, rotated_from_key_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    key_id,
                    user_id,
                    name,
                    fingerprint,
                    key_reference,
                    json.dumps(list(normalized_scopes), separators=(",", ":")),
                    now_text,
                    now_text,
                    expires_at,
                    rotated_from_key_id,
                ),
            )
        record = self.get_api_key(user_id=user_id, key_id=key_id)
        if record is None:
            raise RuntimeError("Created API key could not be loaded.")
        return record

    def rotate_api_key(
        self,
        *,
        user_id: str,
        old_key_id: str,
        new_key_id: str,
        raw_api_key: str,
        expires_in_seconds: int | None,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        old_key_id = self._validate_text(old_key_id, "API key ID", 128)
        new_key_id = self._validate_text(new_key_id, "New API key ID", 128)
        parsed_id, _ = parse_api_key(raw_api_key)
        if parsed_id != new_key_id:
            raise ValueError("API key identifier does not match its token.")
        expires_at = self._expiry_from_seconds(expires_in_seconds)
        now_text = self._now().isoformat()
        fingerprint = fingerprint_api_key(raw_api_key)
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            old = connection.execute(
                f"""
                SELECT * FROM {API_KEY_TABLE}
                WHERE user_id = ? AND key_id = ?
                """,
                (user_id, old_key_id),
            ).fetchone()
            if old is None or old["status"] != "active":
                raise KeyError("Active API key was not found.")
            connection.execute(
                f"""
                UPDATE {API_KEY_TABLE}
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE user_id = ? AND key_id = ?
                """,
                (now_text, now_text, user_id, old_key_id),
            )
            connection.execute(
                f"""
                INSERT INTO {API_KEY_TABLE} (
                    key_id, user_id, name, key_fingerprint, key_reference,
                    scopes_json, status, created_at, updated_at, expires_at,
                    last_used_at, last_ip, revoked_at, rotated_from_key_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    new_key_id,
                    user_id,
                    old["name"],
                    fingerprint,
                    new_key_id[:12],
                    old["scopes_json"],
                    now_text,
                    now_text,
                    expires_at,
                    old_key_id,
                ),
            )
        record = self.get_api_key(user_id=user_id, key_id=new_key_id)
        if record is None:
            raise RuntimeError("Rotated API key could not be loaded.")
        return record

    def get_api_key(
        self,
        *,
        user_id: str,
        key_id: str,
    ) -> dict[str, Any] | None:
        user_id = self._validate_text(user_id, "User ID", 128)
        key_id = self._validate_text(key_id, "API key ID", 128)
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            row = connection.execute(
                f"SELECT * FROM {API_KEY_TABLE} WHERE user_id = ? AND key_id = ?",
                (user_id, key_id),
            ).fetchone()
        return self._api_key_row_to_dict(row)

    def list_api_keys(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        user_id = self._validate_text(user_id, "User ID", 128)
        limit = self._validate_limit(limit)
        conditions = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if status is not None:
            status = self._validate_api_key_status(status)
            conditions.append("status = ?")
            parameters.append(status)
        parameters.append(limit)
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            rows = connection.execute(
                f"""
                SELECT * FROM {API_KEY_TABLE}
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        return [self._api_key_row_to_dict(row) for row in rows]

    def authenticate_api_key(
        self,
        *,
        raw_api_key: str,
        client_ip: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            key_id, _ = parse_api_key(raw_api_key)
            supplied_fingerprint = fingerprint_api_key(raw_api_key)
        except (TypeError, ValueError):
            return None
        try:
            normalized_ip = normalize_ip_address(client_ip)
        except (TypeError, ValueError):
            normalized_ip = None
        now_text = self._now().isoformat()
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            row = connection.execute(
                f"SELECT * FROM {API_KEY_TABLE} WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or not hmac.compare_digest(
                    supplied_fingerprint, row["key_fingerprint"]
                )
            ):
                return None
            user = connection.execute(
                f"SELECT * FROM {USER_TABLE} WHERE user_id = ?",
                (row["user_id"],),
            ).fetchone()
            if user is None or user["status"] != "active":
                return None
            connection.execute(
                f"""
                UPDATE {API_KEY_TABLE}
                SET updated_at = ?, last_used_at = ?, last_ip = ?
                WHERE key_id = ? AND status = 'active'
                """,
                (now_text, now_text, normalized_ip, key_id),
            )
            updated = connection.execute(
                f"SELECT * FROM {API_KEY_TABLE} WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            user_dict = self._user_mapping_to_dict(user)
        return {
            "api_key": self._api_key_row_to_dict(updated),
            "user": user_dict,
        }

    def revoke_api_key(
        self,
        *,
        user_id: str,
        key_id: str,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        key_id = self._validate_text(key_id, "API key ID", 128)
        now_text = self._now().isoformat()
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            row = connection.execute(
                f"SELECT status FROM {API_KEY_TABLE} WHERE user_id = ? AND key_id = ?",
                (user_id, key_id),
            ).fetchone()
            if row is None:
                raise KeyError("API key was not found.")
            if row["status"] == "active":
                connection.execute(
                    f"""
                    UPDATE {API_KEY_TABLE}
                    SET status = 'revoked', updated_at = ?, revoked_at = ?
                    WHERE user_id = ? AND key_id = ?
                    """,
                    (now_text, now_text, user_id, key_id),
                )
        record = self.get_api_key(user_id=user_id, key_id=key_id)
        if record is None:
            raise RuntimeError("Revoked API key could not be loaded.")
        return record

    def revoke_all_api_keys(self, *, user_id: str) -> int:
        user_id = self._validate_text(user_id, "User ID", 128)
        now_text = self._now().isoformat()
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            cursor = connection.execute(
                f"""
                UPDATE {API_KEY_TABLE}
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE user_id = ? AND status = 'active'
                """,
                (now_text, now_text, user_id),
            )
        return int(cursor.rowcount)

    def count_active_api_keys(self, *, user_id: str) -> int:
        user_id = self._validate_text(user_id, "User ID", 128)
        with self._connection() as connection:
            self._expire_api_keys_locked(connection)
            value = connection.execute(
                f"""
                SELECT COUNT(*) FROM {API_KEY_TABLE}
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            ).fetchone()[0]
        return int(value)

    def clear(self) -> None:
        with self._connection() as connection:
            connection.execute(f"DELETE FROM {SESSION_DEVICE_TABLE}")
            connection.execute(f"DELETE FROM {API_KEY_TABLE}")
            connection.execute(f"DELETE FROM {DEVICE_TABLE}")

    def _expire_api_keys_locked(self, connection: sqlite3.Connection) -> int:
        now_text = self._now().isoformat()
        cursor = connection.execute(
            f"""
            UPDATE {API_KEY_TABLE}
            SET status = 'expired', updated_at = ?
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND expires_at <= ?
            """,
            (now_text, now_text),
        )
        return int(cursor.rowcount)

    def _expiry_from_seconds(self, expires_in_seconds: int | None) -> str | None:
        if expires_in_seconds is None:
            return None
        if isinstance(expires_in_seconds, bool) or not isinstance(
            expires_in_seconds, int
        ):
            raise TypeError("API key expiry must be an integer number of seconds.")
        if not 60 <= expires_in_seconds <= 315360000:
            raise ValueError(
                "API key expiry must be between 60 and 315360000 seconds."
            )
        return (self._now() + timedelta(seconds=expires_in_seconds)).isoformat()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _device_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "device_id": row["device_id"],
            "user_id": row["user_id"],
            "device_name": row["device_name"],
            "status": row["status"],
            "trusted": row["status"] == "trusted",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "trusted_at": row["trusted_at"],
            "revoked_at": row["revoked_at"],
            "last_ip": row["last_ip"],
            "last_user_agent": row["last_user_agent"],
            "last_session_id": row["last_session_id"],
            "client_ref": row["client_ref_fingerprint"][:12],
        }

    @staticmethod
    def _api_key_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            scopes = normalize_api_key_scopes(
                json.loads(row["scopes_json"]), require_one=False
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            scopes = ()
        return {
            "key_id": row["key_id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "key_ref": row["key_reference"],
            "scopes": list(scopes),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"],
            "last_ip": row["last_ip"],
            "revoked_at": row["revoked_at"],
            "rotated_from_key_id": row["rotated_from_key_id"],
        }

    @staticmethod
    def _user_mapping_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "status": row["status"],
        }

    @staticmethod
    def _validate_text(value: str, field_name: str, maximum_length: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text.")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty.")
        if len(normalized) > maximum_length:
            raise ValueError(
                f"{field_name} cannot exceed {maximum_length} characters."
            )
        return normalized

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("Limit must be an integer.")
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000.")
        return limit

    @staticmethod
    def _validate_max_active_keys(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("Maximum active API keys must be an integer.")
        if not 1 <= limit <= 100:
            raise ValueError("Maximum active API keys must be between 1 and 100.")
        return limit

    @staticmethod
    def _validate_device_status(status: str) -> str:
        if not isinstance(status, str):
            raise TypeError("Device status must be text.")
        normalized = status.strip().lower()
        if normalized not in DEVICE_STATUSES:
            raise ValueError(
                "Device status must be one of: "
                + ", ".join(sorted(DEVICE_STATUSES))
                + "."
            )
        return normalized

    @staticmethod
    def _validate_api_key_status(status: str) -> str:
        if not isinstance(status, str):
            raise TypeError("API key status must be text.")
        normalized = status.strip().lower()
        if normalized not in API_KEY_STATUSES:
            raise ValueError(
                "API key status must be one of: "
                + ", ".join(sorted(API_KEY_STATUSES))
                + "."
            )
        return normalized


device_security_store = SQLiteDeviceSecurityStore()


__all__ = [
    "API_KEY_STATUSES",
    "API_KEY_TABLE",
    "DEVICE_STATUSES",
    "DEVICE_TABLE",
    "SESSION_DEVICE_TABLE",
    "SQLiteDeviceSecurityStore",
    "device_security_store",
]
