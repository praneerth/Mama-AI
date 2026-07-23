"""
Persistent user-account and authentication-session storage for Mama AI.

This module is storage-only. Existing single-owner Bearer authentication
remains unchanged until the account and session service layer is added.

Security properties:
- Passwords are stored only as salted scrypt hashes.
- Refresh tokens are stored only as SHA-256 fingerprints.
- Raw passwords, refresh tokens, and access tokens are never persisted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database.database import DATABASE_PATH


USER_TABLE = "user_accounts"
SESSION_TABLE = "authentication_sessions"

USER_STATUSES = {"active", "disabled", "locked"}
SESSION_STATUSES = {"active", "revoked", "expired"}

PASSWORD_MINIMUM_LENGTH = 12
PASSWORD_MAXIMUM_LENGTH = 1024
REFRESH_TOKEN_MINIMUM_LENGTH = 32
REFRESH_TOKEN_MAXIMUM_LENGTH = 2048
SESSION_MINIMUM_SECONDS = 300
SESSION_MAXIMUM_SECONDS = 7776000

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise TypeError("Email address must be text.")

    normalized = email.strip().casefold()

    if not normalized:
        raise ValueError("Email address cannot be empty.")

    if len(normalized) > 320:
        raise ValueError("Email address cannot exceed 320 characters.")

    if EMAIL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Email address is invalid.")

    return normalized


def _validate_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("Password must be text.")

    if len(password) < PASSWORD_MINIMUM_LENGTH:
        raise ValueError(
            "Password must contain at least "
            f"{PASSWORD_MINIMUM_LENGTH} characters."
        )

    if len(password) > PASSWORD_MAXIMUM_LENGTH:
        raise ValueError(
            "Password cannot exceed "
            f"{PASSWORD_MAXIMUM_LENGTH} characters."
        )

    return password


def _encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_bytes(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    """Return a versioned salted scrypt password hash."""

    password = _validate_password(password)
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )

    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            str(SCRYPT_DKLEN),
            _encode_bytes(salt),
            _encode_bytes(digest),
        ]
    )


def verify_password_hash(password: str, encoded_hash: str) -> bool:
    """Verify a password against one stored scrypt hash."""

    try:
        password = _validate_password(password)

        if not isinstance(encoded_hash, str):
            return False

        parts = encoded_hash.split("$")

        if len(parts) != 7:
            return False

        algorithm, n_text, r_text, p_text, dklen_text, salt_text, digest_text = parts

        if algorithm != "scrypt":
            return False

        n_value = int(n_text)
        r_value = int(r_text)
        p_value = int(p_text)
        dklen_value = int(dklen_text)

        if n_value < 2 or n_value > 1048576 or n_value & (n_value - 1):
            return False

        if not 1 <= r_value <= 64 or not 1 <= p_value <= 32:
            return False

        if not 16 <= dklen_value <= 128:
            return False

        salt = _decode_bytes(salt_text)
        expected = _decode_bytes(digest_text)

        if len(expected) != dklen_value:
            return False

        supplied = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n_value,
            r=r_value,
            p=p_value,
            dklen=dklen_value,
        )

        return hmac.compare_digest(supplied, expected)

    except (TypeError, ValueError, OverflowError, MemoryError):
        return False


def fingerprint_refresh_token(refresh_token: str) -> str:
    if not isinstance(refresh_token, str):
        raise TypeError("Refresh token must be text.")

    token = refresh_token.strip()

    if len(token) < REFRESH_TOKEN_MINIMUM_LENGTH:
        raise ValueError(
            "Refresh token must contain at least "
            f"{REFRESH_TOKEN_MINIMUM_LENGTH} characters."
        )

    if len(token) > REFRESH_TOKEN_MAXIMUM_LENGTH:
        raise ValueError(
            "Refresh token cannot exceed "
            f"{REFRESH_TOKEN_MAXIMUM_LENGTH} characters."
        )

    return hashlib.sha256(
        ("mama-ai:refresh-token:" + token).encode("utf-8")
    ).hexdigest()


class SQLiteAuthenticationStore:
    """SQLite-backed user-account and refresh-session storage."""

    def __init__(
        self,
        database_path: str | Path = DATABASE_PATH,
        *,
        clock: Callable[[], datetime] | None = None,
        initialize: bool = True,
    ) -> None:
        self.database_path = str(database_path)
        self._clock = clock if clock is not None else utc_datetime

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
                CREATE TABLE IF NOT EXISTS {USER_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'disabled', 'locked')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_user_accounts_status
                ON {USER_TABLE}(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS {SESSION_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    refresh_token_fingerprint TEXT NOT NULL UNIQUE,
                    device_name TEXT,
                    client_ref TEXT,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'revoked', 'expired')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_status
                ON {SESSION_TABLE}(user_id, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry
                ON {SESSION_TABLE}(expires_at);
                """
            )

    def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        password_hash = hash_password(password)
        display_name = self._validate_optional_text(
            display_name,
            "Display name",
            200,
        )
        user_id = uuid4().hex
        now_text = self._now().isoformat()

        try:
            with self._connection() as connection:
                connection.execute(
                    f"""
                    INSERT INTO {USER_TABLE} (
                        user_id,
                        email,
                        display_name,
                        password_hash,
                        status,
                        created_at,
                        updated_at,
                        last_login_at
                    )
                    VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                    """,
                    (
                        user_id,
                        normalized_email,
                        display_name,
                        password_hash,
                        now_text,
                        now_text,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "An account with this email already exists."
            ) from exc

        created = self.get_user(user_id)

        if created is None:
            raise RuntimeError("Created user account could not be loaded.")

        return created

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        user_id = self._validate_text(user_id, "User ID", 128)

        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {USER_TABLE} WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        return self._user_row_to_dict(row)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)

        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {USER_TABLE} WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        return self._user_row_to_dict(row)

    def verify_user_password(self, *, email: str, password: str) -> bool:
        normalized_email = normalize_email(email)

        with self._connection() as connection:
            row = connection.execute(
                f"SELECT password_hash, status FROM {USER_TABLE} WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        if row is None or row["status"] != "active":
            return False

        return verify_password_hash(password, row["password_hash"])


    def change_password(
        self,
        *,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        """
        Atomically replace one account password and revoke all sessions.

        The current password is verified inside the same transaction used
        to replace the stored hash and revoke active sessions.
        """

        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )

        if not isinstance(
            current_password,
            str,
        ):
            raise PermissionError(
                "Current password is invalid."
            )

        if not isinstance(
            new_password,
            str,
        ):
            raise TypeError(
                "New password must be text."
            )

        if secrets.compare_digest(
            current_password,
            new_password,
        ):
            raise ValueError(
                "New password must be different "
                "from the current password."
            )

        new_password_hash = hash_password(
            new_password
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute(
                "BEGIN IMMEDIATE"
            )
            row = connection.execute(
                f"""
                SELECT password_hash, status
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (
                    user_id,
                ),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"User account was not found: {user_id}"
                )

            if (
                row["status"] != "active"
                or not verify_password_hash(
                    current_password,
                    row["password_hash"],
                )
            ):
                raise PermissionError(
                    "Current password is invalid."
                )

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    password_hash = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    new_password_hash,
                    now_text,
                    user_id,
                ),
            )

            revoked_cursor = connection.execute(
                f"""
                UPDATE {SESSION_TABLE}
                SET
                    status = 'revoked',
                    updated_at = ?,
                    revoked_at = ?
                WHERE
                    user_id = ?
                    AND status = 'active'
                """,
                (
                    now_text,
                    now_text,
                    user_id,
                ),
            )
            revoked_sessions = int(
                revoked_cursor.rowcount
            )

        user = self.get_user(
            user_id
        )

        if user is None:
            raise RuntimeError(
                "Updated user account could not be loaded."
            )

        return {
            "user": user,
            "revoked_sessions": revoked_sessions,
        }

    def set_user_status(self, *, user_id: str, status: str) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        status = self._validate_user_status(status)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET status = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (status, now_text, user_id),
            )

            if cursor.rowcount == 0:
                raise KeyError(f"User account was not found: {user_id}")

            if status != "active":
                connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET
                        status = 'revoked',
                        updated_at = ?,
                        revoked_at = COALESCE(revoked_at, ?)
                    WHERE user_id = ? AND status = 'active'
                    """,
                    (now_text, now_text, user_id),
                )

        updated = self.get_user(user_id)

        if updated is None:
            raise RuntimeError("Updated user account could not be loaded.")

        return updated

    def record_login_success(self, user_id: str) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET last_login_at = ?, updated_at = ?
                WHERE user_id = ? AND status = 'active'
                """,
                (now_text, now_text, user_id),
            )

            if cursor.rowcount == 0:
                raise KeyError(
                    f"Active user account was not found: {user_id}"
                )

        updated = self.get_user(user_id)

        if updated is None:
            raise RuntimeError("Updated user account could not be loaded.")

        return updated

    def create_session(
        self,
        *,
        user_id: str,
        refresh_token: str,
        device_name: str | None = None,
        client_ref: str | None = None,
        expires_in_seconds: int = 2592000,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        token_fingerprint = fingerprint_refresh_token(refresh_token)
        device_name = self._validate_optional_text(
            device_name,
            "Device name",
            200,
        )
        client_ref = self._validate_optional_text(
            client_ref,
            "Client reference",
            256,
        )
        expires_in_seconds = self._validate_session_expiry(
            expires_in_seconds
        )

        user = self.get_user(user_id)

        if user is None:
            raise KeyError(f"User account was not found: {user_id}")

        if user["status"] != "active":
            raise PermissionError(
                "Sessions can be created only for active user accounts."
            )

        session_id = uuid4().hex
        now = self._now()
        now_text = now.isoformat()
        expires_at = (
            now + timedelta(seconds=expires_in_seconds)
        ).isoformat()

        try:
            with self._connection() as connection:
                connection.execute(
                    f"""
                    INSERT INTO {SESSION_TABLE} (
                        session_id,
                        user_id,
                        refresh_token_fingerprint,
                        device_name,
                        client_ref,
                        status,
                        created_at,
                        updated_at,
                        last_seen_at,
                        expires_at,
                        revoked_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, NULL)
                    """,
                    (
                        session_id,
                        user_id,
                        token_fingerprint,
                        device_name,
                        client_ref,
                        now_text,
                        now_text,
                        now_text,
                        expires_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "This refresh token is already registered to a session."
            ) from exc

        created = self.get_session(session_id)

        if created is None:
            raise RuntimeError(
                "Created authentication session could not be loaded."
            )

        return created

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session_id = self._validate_text(session_id, "Session ID", 128)

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            row = connection.execute(
                f"SELECT * FROM {SESSION_TABLE} WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        return self._session_row_to_dict(row)

    def get_session_by_refresh_token(
        self,
        refresh_token: str,
    ) -> dict[str, Any] | None:
        token_fingerprint = fingerprint_refresh_token(refresh_token)

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            row = connection.execute(
                f"""
                SELECT *
                FROM {SESSION_TABLE}
                WHERE refresh_token_fingerprint = ?
                """,
                (token_fingerprint,),
            ).fetchone()

        return self._session_row_to_dict(row)

    def validate_refresh_token(
        self,
        refresh_token: str,
    ) -> dict[str, Any] | None:
        token_fingerprint = fingerprint_refresh_token(refresh_token)

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            row = connection.execute(
                f"""
                SELECT s.*
                FROM {SESSION_TABLE} AS s
                INNER JOIN {USER_TABLE} AS u
                    ON u.user_id = s.user_id
                WHERE
                    s.refresh_token_fingerprint = ?
                    AND s.status = 'active'
                    AND u.status = 'active'
                """,
                (token_fingerprint,),
            ).fetchone()

        return self._session_row_to_dict(row)


    def rotate_refresh_token(
        self,
        *,
        current_refresh_token: str,
        new_refresh_token: str,
        expires_in_seconds: int = 2592000,
    ) -> dict[str, Any] | None:
        """
        Atomically rotate one active refresh token.

        None is returned when the current token is unknown, expired,
        revoked, or belongs to a non-active account.
        """

        current_fingerprint = fingerprint_refresh_token(
            current_refresh_token
        )
        new_fingerprint = fingerprint_refresh_token(
            new_refresh_token
        )
        expires_in_seconds = self._validate_session_expiry(
            expires_in_seconds
        )

        if hmac.compare_digest(
            current_fingerprint,
            new_fingerprint,
        ):
            raise ValueError(
                "The replacement refresh token must be different."
            )

        now = self._now()
        now_text = now.isoformat()
        expires_at = (
            now
            + timedelta(
                seconds=expires_in_seconds
            )
        ).isoformat()

        try:
            with self._connection() as connection:
                connection.execute(
                    "BEGIN IMMEDIATE"
                )
                self._expire_sessions_locked(
                    connection
                )

                row = connection.execute(
                    f"""
                    SELECT
                        s.session_id,
                        s.user_id
                    FROM {SESSION_TABLE} AS s
                    INNER JOIN {USER_TABLE} AS u
                        ON u.user_id = s.user_id
                    WHERE
                        s.refresh_token_fingerprint = ?
                        AND s.status = 'active'
                        AND u.status = 'active'
                    """,
                    (
                        current_fingerprint,
                    ),
                ).fetchone()

                if row is None:
                    return None

                cursor = connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET
                        refresh_token_fingerprint = ?,
                        updated_at = ?,
                        last_seen_at = ?,
                        expires_at = ?
                    WHERE
                        session_id = ?
                        AND refresh_token_fingerprint = ?
                        AND status = 'active'
                    """,
                    (
                        new_fingerprint,
                        now_text,
                        now_text,
                        expires_at,
                        row["session_id"],
                        current_fingerprint,
                    ),
                )

                if cursor.rowcount != 1:
                    return None

                session_id = row["session_id"]

        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "The replacement refresh token is already registered."
            ) from exc

        return self.get_session(
            session_id
        )

    def touch_session(self, session_id: str) -> dict[str, Any]:
        session_id = self._validate_text(session_id, "Session ID", 128)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            cursor = connection.execute(
                f"""
                UPDATE {SESSION_TABLE}
                SET last_seen_at = ?, updated_at = ?
                WHERE session_id = ? AND status = 'active'
                """,
                (now_text, now_text, session_id),
            )

            if cursor.rowcount == 0:
                raise KeyError(
                    "Active authentication session was not found: "
                    f"{session_id}"
                )

        updated = self.get_session(session_id)

        if updated is None:
            raise RuntimeError(
                "Updated authentication session could not be loaded."
            )

        return updated

    def revoke_session(self, session_id: str) -> dict[str, Any]:
        session_id = self._validate_text(session_id, "Session ID", 128)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            row = connection.execute(
                f"SELECT status FROM {SESSION_TABLE} WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"Authentication session was not found: {session_id}"
                )

            if row["status"] == "active":
                connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET status = 'revoked', updated_at = ?, revoked_at = ?
                    WHERE session_id = ?
                    """,
                    (now_text, now_text, session_id),
                )

        updated = self.get_session(session_id)

        if updated is None:
            raise RuntimeError(
                "Revoked authentication session could not be loaded."
            )

        return updated


    def revoke_user_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Revoke one session only when it belongs to the supplied user.

        A missing session and another user's session intentionally produce
        the same KeyError so callers cannot enumerate session ownership.
        """

        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )
        session_id = self._validate_text(
            session_id,
            "Session ID",
            128,
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            self._expire_sessions_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT status
                FROM {SESSION_TABLE}
                WHERE
                    session_id = ?
                    AND user_id = ?
                """,
                (
                    session_id,
                    user_id,
                ),
            ).fetchone()

            if row is None:
                raise KeyError(
                    "Authentication session was not found."
                )

            if row["status"] == "active":
                connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET
                        status = 'revoked',
                        updated_at = ?,
                        revoked_at = ?
                    WHERE
                        session_id = ?
                        AND user_id = ?
                    """,
                    (
                        now_text,
                        now_text,
                        session_id,
                        user_id,
                    ),
                )

        updated = self.get_session(
            session_id
        )

        if updated is None:
            raise RuntimeError(
                "Revoked authentication session "
                "could not be loaded."
            )

        return updated

    def revoke_all_sessions(self, user_id: str) -> int:
        user_id = self._validate_text(user_id, "User ID", 128)
        now_text = self._now().isoformat()

        if self.get_user(user_id) is None:
            raise KeyError(f"User account was not found: {user_id}")

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            cursor = connection.execute(
                f"""
                UPDATE {SESSION_TABLE}
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE user_id = ? AND status = 'active'
                """,
                (now_text, now_text, user_id),
            )

        return int(cursor.rowcount)

    def list_sessions(
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
            status = self._validate_session_status(status)
            conditions.append("status = ?")
            parameters.append(status)

        parameters.append(limit)

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            rows = connection.execute(
                f"""
                SELECT *
                FROM {SESSION_TABLE}
                WHERE {" AND ".join(conditions)}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()

        return [self._session_row_to_dict(row) for row in rows]

    def count_sessions(
        self,
        *,
        user_id: str,
        status: str | None = None,
    ) -> int:
        user_id = self._validate_text(user_id, "User ID", 128)
        conditions = ["user_id = ?"]
        parameters: list[Any] = [user_id]

        if status is not None:
            status = self._validate_session_status(status)
            conditions.append("status = ?")
            parameters.append(status)

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {SESSION_TABLE}
                WHERE {" AND ".join(conditions)}
                """,
                tuple(parameters),
            ).fetchone()

        return int(row["total"])

    def delete_expired_sessions(self, *, limit: int = 1000) -> int:
        limit = self._validate_limit(limit)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            self._expire_sessions_locked(connection)
            cursor = connection.execute(
                f"""
                DELETE FROM {SESSION_TABLE}
                WHERE sequence_id IN (
                    SELECT sequence_id
                    FROM {SESSION_TABLE}
                    WHERE status = 'expired' OR expires_at <= ?
                    ORDER BY sequence_id ASC
                    LIMIT ?
                )
                """,
                (now_text, limit),
            )

        return int(cursor.rowcount)

    def clear(self) -> None:
        with self._connection() as connection:
            connection.execute(f"DELETE FROM {SESSION_TABLE}")
            connection.execute(f"DELETE FROM {USER_TABLE}")

    def _expire_sessions_locked(self, connection: sqlite3.Connection) -> int:
        now_text = self._now().isoformat()
        cursor = connection.execute(
            f"""
            UPDATE {SESSION_TABLE}
            SET status = 'expired', updated_at = ?
            WHERE status = 'active' AND expires_at <= ?
            """,
            (now_text, now_text),
        )
        return int(cursor.rowcount)

    def _now(self) -> datetime:
        current = self._clock()

        if not isinstance(current, datetime):
            raise TypeError("Authentication clock must return datetime.")

        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        return current.astimezone(timezone.utc)

    @staticmethod
    def _user_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
        }

    @staticmethod
    def _session_row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        fingerprint = row["refresh_token_fingerprint"]

        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "token_ref": fingerprint[:12],
            "device_name": row["device_name"],
            "client_ref": row["client_ref"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_seen_at": row["last_seen_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
        }

    @staticmethod
    def _validate_text(
        value: str,
        field_name: str,
        maximum_length: int,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text.")

        value = value.strip()

        if not value:
            raise ValueError(f"{field_name} cannot be empty.")

        if len(value) > maximum_length:
            raise ValueError(
                f"{field_name} cannot exceed {maximum_length} characters."
            )

        return value

    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        field_name: str,
        maximum_length: int,
    ) -> str | None:
        if value is None:
            return None

        return cls._validate_text(value, field_name, maximum_length)

    @classmethod
    def _validate_user_status(cls, status: str) -> str:
        status = cls._validate_text(status, "User status", 32).lower()

        if status not in USER_STATUSES:
            raise ValueError(f"Unsupported user status: {status}")

        return status

    @classmethod
    def _validate_session_status(cls, status: str) -> str:
        status = cls._validate_text(status, "Session status", 32).lower()

        if status not in SESSION_STATUSES:
            raise ValueError(f"Unsupported session status: {status}")

        return status

    @staticmethod
    def _validate_session_expiry(expires_in_seconds: int) -> int:
        if isinstance(expires_in_seconds, bool) or not isinstance(
            expires_in_seconds,
            int,
        ):
            raise TypeError("Session expiry must be an integer.")

        if not SESSION_MINIMUM_SECONDS <= expires_in_seconds <= SESSION_MAXIMUM_SECONDS:
            raise ValueError(
                "Session expiry must be between "
                f"{SESSION_MINIMUM_SECONDS} and "
                f"{SESSION_MAXIMUM_SECONDS} seconds."
            )

        return expires_in_seconds

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("Limit must be an integer.")

        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000.")

        return limit


authentication_store = SQLiteAuthenticationStore()


__all__ = [
    "PASSWORD_MAXIMUM_LENGTH",
    "PASSWORD_MINIMUM_LENGTH",
    "REFRESH_TOKEN_MAXIMUM_LENGTH",
    "REFRESH_TOKEN_MINIMUM_LENGTH",
    "SESSION_STATUSES",
    "SESSION_TABLE",
    "SQLiteAuthenticationStore",
    "USER_STATUSES",
    "USER_TABLE",
    "authentication_store",
    "fingerprint_refresh_token",
    "hash_password",
    "normalize_email",
    "verify_password_hash",
]