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

from app.core.rbac import (
    ACCOUNT_ROLES,
    ROLE_ADMIN,
    ROLE_USER,
    validate_role,
)
from app.database.database import DATABASE_PATH


USER_TABLE = "user_accounts"
USER_ROLE_TABLE = "user_account_roles"
SESSION_TABLE = "authentication_sessions"
ACCOUNT_ACTION_TOKEN_TABLE = "account_action_tokens"
TWO_FACTOR_CHALLENGE_TABLE = "authentication_two_factor_challenges"
TWO_FACTOR_RECOVERY_CODE_TABLE = "authentication_two_factor_recovery_codes"

USER_STATUSES = {"active", "disabled", "locked"}
SESSION_STATUSES = {"active", "revoked", "expired"}
ACCOUNT_ACTION_TOKEN_PURPOSES = {
    "email_verification",
    "password_reset",
}
ACCOUNT_ACTION_TOKEN_STATUSES = {
    "active",
    "consumed",
    "revoked",
    "expired",
}
TWO_FACTOR_CHALLENGE_STATUSES = {
    "active",
    "consumed",
    "revoked",
    "expired",
}
TWO_FACTOR_RECOVERY_CODE_STATUSES = {
    "active",
    "consumed",
    "revoked",
}

PASSWORD_MINIMUM_LENGTH = 12
PASSWORD_MAXIMUM_LENGTH = 1024
REFRESH_TOKEN_MINIMUM_LENGTH = 32
REFRESH_TOKEN_MAXIMUM_LENGTH = 2048
SESSION_MINIMUM_SECONDS = 300
SESSION_MAXIMUM_SECONDS = 7776000
ACCOUNT_ACTION_TOKEN_MINIMUM_LENGTH = 32
ACCOUNT_ACTION_TOKEN_MAXIMUM_LENGTH = 2048
ACCOUNT_ACTION_TOKEN_MINIMUM_SECONDS = 60
ACCOUNT_ACTION_TOKEN_MAXIMUM_SECONDS = 604800
TWO_FACTOR_CHALLENGE_MINIMUM_SECONDS = 60
TWO_FACTOR_CHALLENGE_MAXIMUM_SECONDS = 900

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


def fingerprint_account_action_token(
    token: str,
    *,
    purpose: str,
) -> str:
    if not isinstance(token, str):
        raise TypeError("Account action token must be text.")

    token = token.strip()

    if len(token) < ACCOUNT_ACTION_TOKEN_MINIMUM_LENGTH:
        raise ValueError(
            "Account action token must contain at least "
            f"{ACCOUNT_ACTION_TOKEN_MINIMUM_LENGTH} characters."
        )

    if len(token) > ACCOUNT_ACTION_TOKEN_MAXIMUM_LENGTH:
        raise ValueError(
            "Account action token cannot exceed "
            f"{ACCOUNT_ACTION_TOKEN_MAXIMUM_LENGTH} characters."
        )

    purpose = purpose.strip().lower() if isinstance(purpose, str) else ""

    if purpose not in ACCOUNT_ACTION_TOKEN_PURPOSES:
        raise ValueError(
            f"Unsupported account action token purpose: {purpose}"
        )

    return hashlib.sha256(
        (
            "mama-ai:account-action-token:"
            + purpose
            + ":"
            + token
        ).encode("utf-8")
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
                    last_login_at TEXT,
                    email_verified_at TEXT,
                    failed_login_count INTEGER NOT NULL DEFAULT 0
                        CHECK (failed_login_count >= 0),
                    failed_login_window_started_at TEXT,
                    last_failed_login_at TEXT,
                    locked_until TEXT,
                    two_factor_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK (two_factor_enabled IN (0, 1)),
                    two_factor_secret_salt TEXT,
                    two_factor_pending_salt TEXT,
                    two_factor_confirmed_at TEXT,
                    two_factor_updated_at TEXT,
                    two_factor_last_counter INTEGER
                        CHECK (two_factor_last_counter IS NULL OR two_factor_last_counter >= 0)
                );

                CREATE INDEX IF NOT EXISTS idx_user_accounts_status
                ON {USER_TABLE}(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS {USER_ROLE_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL
                        CHECK (role IN ('admin', 'auditor', 'user')),
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, role),
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_user_account_roles_role
                ON {USER_ROLE_TABLE}(role, user_id);

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

                CREATE TABLE IF NOT EXISTS {ACCOUNT_ACTION_TOKEN_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    purpose TEXT NOT NULL
                        CHECK (purpose IN ('email_verification', 'password_reset')),
                    token_fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'consumed', 'revoked', 'expired')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_account_action_tokens_user
                ON {ACCOUNT_ACTION_TOKEN_TABLE}(
                    user_id,
                    purpose,
                    status,
                    updated_at DESC
                );

                CREATE INDEX IF NOT EXISTS idx_account_action_tokens_expiry
                ON {ACCOUNT_ACTION_TOKEN_TABLE}(expires_at);

                CREATE TABLE IF NOT EXISTS {TWO_FACTOR_CHALLENGE_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenge_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    token_fingerprint TEXT NOT NULL UNIQUE,
                    device_name TEXT,
                    client_ref TEXT,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'consumed', 'revoked', 'expired')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_two_factor_challenges_user
                ON {TWO_FACTOR_CHALLENGE_TABLE}(
                    user_id,
                    status,
                    updated_at DESC
                );

                CREATE INDEX IF NOT EXISTS idx_two_factor_challenges_expiry
                ON {TWO_FACTOR_CHALLENGE_TABLE}(expires_at);

                CREATE TABLE IF NOT EXISTS {TWO_FACTOR_RECOVERY_CODE_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    code_fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'consumed', 'revoked')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES {USER_TABLE}(user_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_two_factor_recovery_user
                ON {TWO_FACTOR_RECOVERY_CODE_TABLE}(
                    user_id,
                    status,
                    updated_at DESC
                );
                """
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="email_verified_at",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="failed_login_count",
                column_definition=(
                    "INTEGER NOT NULL DEFAULT 0"
                ),
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name=(
                    "failed_login_window_started_at"
                ),
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="last_failed_login_at",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="locked_until",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_enabled",
                column_definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_secret_salt",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_pending_salt",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_confirmed_at",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_updated_at",
                column_definition="TEXT",
            )
            self._ensure_column_locked(
                connection,
                table_name=USER_TABLE,
                column_name="two_factor_last_counter",
                column_definition="INTEGER",
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                    idx_user_accounts_lockout
                ON {USER_TABLE}(
                    status,
                    locked_until
                )
                """
            )
            now_text = self._now().isoformat()
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {USER_ROLE_TABLE} (
                    user_id,
                    role,
                    created_at
                )
                SELECT user_id, ?, ?
                FROM {USER_TABLE}
                """,
                (ROLE_USER, now_text),
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
                        last_login_at,
                        email_verified_at
                    )
                    VALUES (?, ?, ?, ?, 'active', ?, ?, NULL, NULL)
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
                connection.execute(
                    f"""
                    INSERT INTO {USER_ROLE_TABLE} (
                        user_id, role, created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (user_id, ROLE_USER, now_text),
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
            self._unlock_expired_user_locks_locked(
                connection,
                user_id=user_id,
            )
            row = connection.execute(
                f"SELECT * FROM {USER_TABLE} WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            roles = (
                self._get_user_roles_locked(
                    connection, user_id
                )
                if row is not None
                else ()
            )

        return self._user_row_to_dict(
            row, roles=roles
        )

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)

        with self._connection() as connection:
            self._unlock_expired_user_locks_locked(
                connection,
                email=normalized_email,
            )
            row = connection.execute(
                f"SELECT * FROM {USER_TABLE} WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            roles = (
                self._get_user_roles_locked(
                    connection, row["user_id"]
                )
                if row is not None
                else ()
            )

        return self._user_row_to_dict(
            row, roles=roles
        )

    def verify_user_password(self, *, email: str, password: str) -> bool:
        normalized_email = normalize_email(email)

        with self._connection() as connection:
            self._unlock_expired_user_locks_locked(
                connection,
                email=normalized_email,
            )
            row = connection.execute(
                f"SELECT password_hash, status FROM {USER_TABLE} WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        if row is None or row["status"] != "active":
            return False

        return verify_password_hash(password, row["password_hash"])


    def list_users(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)
        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            status = self._validate_user_status(status)
            conditions.append("u.status = ?")
            parameters.append(status)

        if role is not None:
            role = validate_role(role)
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM {USER_ROLE_TABLE} r
                    WHERE r.user_id = u.user_id
                    AND r.role = ?
                )
                """
            )
            parameters.append(role)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        parameters.append(limit)

        with self._connection() as connection:
            self._unlock_expired_user_locks_locked(
                connection
            )
            rows = connection.execute(
                f"""
                SELECT u.*
                FROM {USER_TABLE} u
                {where_clause}
                ORDER BY u.sequence_id ASC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
            return [
                self._user_row_to_dict(
                    row,
                    roles=self._get_user_roles_locked(
                        connection, row["user_id"]
                    ),
                )
                for row in rows
            ]

    def count_users(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
    ) -> int:
        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            status = self._validate_user_status(status)
            conditions.append("u.status = ?")
            parameters.append(status)

        if role is not None:
            role = validate_role(role)
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM {USER_ROLE_TABLE} r
                    WHERE r.user_id = u.user_id
                    AND r.role = ?
                )
                """
            )
            parameters.append(role)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        with self._connection() as connection:
            self._unlock_expired_user_locks_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {USER_TABLE} u
                {where_clause}
                """,
                tuple(parameters),
            ).fetchone()

        return int(row["total"])

    def assign_user_role(
        self,
        *,
        user_id: str,
        role: str,
    ) -> dict[str, Any]:
        user_id = self._validate_text(
            user_id, "User ID", 128
        )
        role = validate_role(role)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                f"SELECT 1 FROM {USER_TABLE} WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if exists is None:
                raise KeyError(
                    f"User account was not found: {user_id}"
                )

            cursor = connection.execute(
                f"""
                INSERT OR IGNORE INTO {USER_ROLE_TABLE} (
                    user_id, role, created_at
                )
                VALUES (?, ?, ?)
                """,
                (user_id, role, now_text),
            )
            changed = int(cursor.rowcount) > 0

            if changed:
                connection.execute(
                    f"""
                    UPDATE {USER_TABLE}
                    SET updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now_text, user_id),
                )

        user = self.get_user(user_id)

        if user is None:
            raise RuntimeError(
                "Updated user account could not be loaded."
            )

        return {
            "user": user,
            "changed": changed,
            "role": role,
        }

    def remove_user_role_by_administrator(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        role: str,
    ) -> dict[str, Any]:
        actor_user_id = self._validate_text(
            actor_user_id, "Actor user ID", 128
        )
        user_id = self._validate_text(
            user_id, "User ID", 128
        )
        role = validate_role(role)

        if role == ROLE_USER:
            raise PermissionError(
                "The baseline user role cannot be removed."
            )

        if (
            role == ROLE_ADMIN
            and secrets.compare_digest(
                actor_user_id, user_id
            )
        ):
            raise PermissionError(
                "Administrators cannot remove their own admin role."
            )

        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT status
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"User account was not found: {user_id}"
                )

            existing = connection.execute(
                f"""
                SELECT 1
                FROM {USER_ROLE_TABLE}
                WHERE user_id = ? AND role = ?
                """,
                (user_id, role),
            ).fetchone()

            if existing is None:
                changed = False
            else:
                if (
                    role == ROLE_ADMIN
                    and row["status"] == "active"
                    and self._count_active_admins_locked(
                        connection
                    ) <= 1
                ):
                    raise PermissionError(
                        "The final active administrator role cannot be removed."
                    )

                cursor = connection.execute(
                    f"""
                    DELETE FROM {USER_ROLE_TABLE}
                    WHERE user_id = ? AND role = ?
                    """,
                    (user_id, role),
                )
                changed = int(cursor.rowcount) > 0

                if changed:
                    connection.execute(
                        f"""
                        UPDATE {USER_TABLE}
                        SET updated_at = ?
                        WHERE user_id = ?
                        """,
                        (now_text, user_id),
                    )

        user = self.get_user(user_id)

        if user is None:
            raise RuntimeError(
                "Updated user account could not be loaded."
            )

        return {
            "user": user,
            "changed": changed,
            "role": role,
        }

    def set_user_status_by_administrator(
        self,
        *,
        actor_user_id: str,
        user_id: str,
        status: str,
        allowed_current_statuses: set[str],
    ) -> dict[str, Any]:
        actor_user_id = self._validate_text(
            actor_user_id, "Actor user ID", 128
        )
        user_id = self._validate_text(
            user_id, "User ID", 128
        )
        status = self._validate_user_status(status)

        if not isinstance(
            allowed_current_statuses, set
        ) or not allowed_current_statuses:
            raise ValueError(
                "Allowed current statuses cannot be empty."
            )

        allowed = {
            self._validate_user_status(value)
            for value in allowed_current_statuses
        }

        if (
            status != "active"
            and secrets.compare_digest(
                actor_user_id, user_id
            )
        ):
            raise PermissionError(
                "Administrators cannot disable or lock their own account."
            )

        now_text = self._now().isoformat()
        revoked_sessions = 0

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT status
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"User account was not found: {user_id}"
                )

            current_status = row["status"]

            if current_status not in allowed:
                raise ValueError(
                    "Account status transition is not allowed."
                )

            roles = self._get_user_roles_locked(
                connection, user_id
            )

            if (
                status != "active"
                and current_status == "active"
                and ROLE_ADMIN in roles
                and self._count_active_admins_locked(
                    connection
                ) <= 1
            ):
                raise PermissionError(
                    "The final active administrator account cannot be disabled."
                )

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    status = ?,
                    failed_login_count = 0,
                    failed_login_window_started_at = NULL,
                    last_failed_login_at = NULL,
                    locked_until = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (status, now_text, user_id),
            )

            if status != "active":
                cursor = connection.execute(
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
                revoked_sessions = int(
                    cursor.rowcount
                )

        user = self.get_user(user_id)

        if user is None:
            raise RuntimeError(
                "Updated user account could not be loaded."
            )

        return {
            "user": user,
            "previous_status": current_status,
            "revoked_sessions": revoked_sessions,
        }


    def get_login_protection_state(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Return account login-protection state without password data."""

        normalized_email = normalize_email(
            email
        )
        now = self._now()

        with self._connection() as connection:
            self._unlock_expired_user_locks_locked(
                connection,
                email=normalized_email,
            )
            row = connection.execute(
                f"""
                SELECT
                    user_id,
                    status,
                    failed_login_count,
                    failed_login_window_started_at,
                    last_failed_login_at,
                    locked_until
                FROM {USER_TABLE}
                WHERE email = ?
                """,
                (
                    normalized_email,
                ),
            ).fetchone()

        if row is None:
            return None

        retry_after_seconds = 0
        locked_until = row["locked_until"]

        if (
            row["status"] == "locked"
            and locked_until
        ):
            try:
                unlock_at = datetime.fromisoformat(
                    locked_until
                )
                if unlock_at.tzinfo is None:
                    unlock_at = unlock_at.replace(
                        tzinfo=timezone.utc
                    )
                retry_after_seconds = max(
                    0,
                    int(
                        (
                            unlock_at.astimezone(
                                timezone.utc
                            )
                            - now
                        ).total_seconds()
                    ),
                )
            except (TypeError, ValueError):
                retry_after_seconds = 0

        return {
            "user_id": row["user_id"],
            "status": row["status"],
            "failed_login_count": int(
                row["failed_login_count"] or 0
            ),
            "failed_login_window_started_at": (
                row["failed_login_window_started_at"]
            ),
            "last_failed_login_at": (
                row["last_failed_login_at"]
            ),
            "locked_until": locked_until,
            "retry_after_seconds": (
                retry_after_seconds
            ),
        }

    def record_login_failure(
        self,
        *,
        email: str,
        failure_limit: int,
        failure_window_seconds: int,
        lockout_seconds: int,
    ) -> dict[str, Any] | None:
        """Atomically record one failed login and start lockout when due."""

        normalized_email = normalize_email(
            email
        )
        self._validate_login_protection_parameters(
            failure_limit=failure_limit,
            failure_window_seconds=(
                failure_window_seconds
            ),
            lockout_seconds=lockout_seconds,
        )
        now = self._now()
        now_text = now.isoformat()

        with self._connection() as connection:
            connection.execute(
                "BEGIN IMMEDIATE"
            )
            self._unlock_expired_user_locks_locked(
                connection,
                email=normalized_email,
            )
            row = connection.execute(
                f"""
                SELECT
                    user_id,
                    status,
                    failed_login_count,
                    failed_login_window_started_at,
                    locked_until
                FROM {USER_TABLE}
                WHERE email = ?
                """,
                (
                    normalized_email,
                ),
            ).fetchone()

            if row is None:
                return None

            if row["status"] != "active":
                locked_until = row["locked_until"]
                retry_after_seconds = 0

                if (
                    row["status"] == "locked"
                    and locked_until
                ):
                    try:
                        unlock_at = datetime.fromisoformat(
                            locked_until
                        )
                        if unlock_at.tzinfo is None:
                            unlock_at = unlock_at.replace(
                                tzinfo=timezone.utc
                            )
                        retry_after_seconds = max(
                            0,
                            int(
                                (
                                    unlock_at.astimezone(
                                        timezone.utc
                                    )
                                    - now
                                ).total_seconds()
                            ),
                        )
                    except (TypeError, ValueError):
                        retry_after_seconds = 0

                return {
                    "user_id": row["user_id"],
                    "status": row["status"],
                    "failed_login_count": int(
                        row["failed_login_count"] or 0
                    ),
                    "failed_login_window_started_at": (
                        row["failed_login_window_started_at"]
                    ),
                    "last_failed_login_at": now_text,
                    "locked_until": locked_until,
                    "retry_after_seconds": (
                        retry_after_seconds
                    ),
                    "lockout_started": False,
                    "already_locked": (
                        row["status"] == "locked"
                    ),
                }

            previous_count = int(
                row["failed_login_count"] or 0
            )
            window_started_at = (
                row["failed_login_window_started_at"]
            )
            inside_window = False

            if window_started_at:
                try:
                    window_start = datetime.fromisoformat(
                        window_started_at
                    )
                    if window_start.tzinfo is None:
                        window_start = window_start.replace(
                            tzinfo=timezone.utc
                        )
                    inside_window = (
                        now
                        < window_start.astimezone(
                            timezone.utc
                        )
                        + timedelta(
                            seconds=(
                                failure_window_seconds
                            )
                        )
                    )
                except (TypeError, ValueError):
                    inside_window = False

            if inside_window:
                failure_count = previous_count + 1
                new_window_start = window_started_at
            else:
                failure_count = 1
                new_window_start = now_text

            lockout_started = (
                failure_count >= failure_limit
            )
            locked_until = None
            new_status = "active"

            if lockout_started:
                new_status = "locked"
                locked_until = (
                    now
                    + timedelta(
                        seconds=lockout_seconds
                    )
                ).isoformat()

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    status = ?,
                    failed_login_count = ?,
                    failed_login_window_started_at = ?,
                    last_failed_login_at = ?,
                    locked_until = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    new_status,
                    failure_count,
                    new_window_start,
                    now_text,
                    locked_until,
                    now_text,
                    row["user_id"],
                ),
            )

            if lockout_started:
                connection.execute(
                    f"""
                    UPDATE {SESSION_TABLE}
                    SET
                        status = 'revoked',
                        updated_at = ?,
                        revoked_at = COALESCE(
                            revoked_at,
                            ?
                        )
                    WHERE
                        user_id = ?
                        AND status = 'active'
                    """,
                    (
                        now_text,
                        now_text,
                        row["user_id"],
                    ),
                )

        return {
            "user_id": row["user_id"],
            "status": new_status,
            "failed_login_count": failure_count,
            "failed_login_window_started_at": (
                new_window_start
            ),
            "last_failed_login_at": now_text,
            "locked_until": locked_until,
            "retry_after_seconds": (
                lockout_seconds
                if lockout_started
                else 0
            ),
            "lockout_started": lockout_started,
            "already_locked": False,
        }

    def get_two_factor_material(
        self,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Return internal two-factor derivation material for the service."""

        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )

        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT
                    user_id,
                    email,
                    status,
                    two_factor_enabled,
                    two_factor_secret_salt,
                    two_factor_pending_salt,
                    two_factor_confirmed_at,
                    two_factor_updated_at,
                    two_factor_last_counter
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "status": row["status"],
            "enabled": bool(row["two_factor_enabled"]),
            "secret_salt": row["two_factor_secret_salt"],
            "pending_salt": row["two_factor_pending_salt"],
            "confirmed_at": row["two_factor_confirmed_at"],
            "updated_at": row["two_factor_updated_at"],
            "last_counter": row["two_factor_last_counter"],
        }

    def start_two_factor_setup(
        self,
        *,
        user_id: str,
        pending_salt: str,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        pending_salt = self._validate_text(
            pending_salt,
            "Two-factor salt",
            512,
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    two_factor_pending_salt = ?,
                    two_factor_updated_at = ?,
                    updated_at = ?
                WHERE
                    user_id = ?
                    AND status = 'active'
                    AND two_factor_enabled = 0
                """,
                (
                    pending_salt,
                    now_text,
                    now_text,
                    user_id,
                ),
            )

            if cursor.rowcount == 0:
                row = connection.execute(
                    f"""
                    SELECT status, two_factor_enabled
                    FROM {USER_TABLE}
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()

                if row is None:
                    raise KeyError(
                        f"User account was not found: {user_id}"
                    )

                if bool(row["two_factor_enabled"]):
                    raise PermissionError(
                        "Two-factor authentication is already enabled."
                    )

                raise PermissionError(
                    "Two-factor setup is unavailable for this account."
                )

        material = self.get_two_factor_material(user_id)
        if material is None:
            raise RuntimeError("Two-factor setup could not be loaded.")
        return material

    def enable_two_factor(
        self,
        *,
        user_id: str,
        pending_salt: str,
        last_counter: int,
        recovery_code_fingerprints: list[str],
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        pending_salt = self._validate_text(
            pending_salt,
            "Two-factor salt",
            512,
        )
        last_counter = self._validate_counter(last_counter)
        fingerprints = self._validate_fingerprints(
            recovery_code_fingerprints
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT
                    status,
                    two_factor_enabled,
                    two_factor_pending_salt
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"User account was not found: {user_id}"
                )

            if row["status"] != "active":
                raise PermissionError(
                    "Two-factor setup is unavailable for this account."
                )

            if bool(row["two_factor_enabled"]):
                raise PermissionError(
                    "Two-factor authentication is already enabled."
                )

            stored_pending = row["two_factor_pending_salt"]
            if (
                not stored_pending
                or not secrets.compare_digest(
                    stored_pending,
                    pending_salt,
                )
            ):
                raise PermissionError(
                    "Two-factor setup must be started again."
                )

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    two_factor_enabled = 1,
                    two_factor_secret_salt = ?,
                    two_factor_pending_salt = NULL,
                    two_factor_confirmed_at = ?,
                    two_factor_updated_at = ?,
                    two_factor_last_counter = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    pending_salt,
                    now_text,
                    now_text,
                    last_counter,
                    now_text,
                    user_id,
                ),
            )
            self._replace_recovery_codes_locked(
                connection,
                user_id=user_id,
                fingerprints=fingerprints,
                now_text=now_text,
            )
            self._revoke_two_factor_challenges_locked(
                connection,
                user_id=user_id,
                now_text=now_text,
            )
            revoked_sessions = self._revoke_user_sessions_locked(
                connection,
                user_id=user_id,
                now_text=now_text,
            )

        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("Enabled account could not be loaded.")
        return {
            "user": user,
            "revoked_sessions": revoked_sessions,
            "recovery_code_count": len(fingerprints),
        }

    def disable_two_factor(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    two_factor_enabled = 0,
                    two_factor_secret_salt = NULL,
                    two_factor_pending_salt = NULL,
                    two_factor_confirmed_at = NULL,
                    two_factor_updated_at = ?,
                    two_factor_last_counter = NULL,
                    updated_at = ?
                WHERE
                    user_id = ?
                    AND status = 'active'
                    AND two_factor_enabled = 1
                """,
                (now_text, now_text, user_id),
            )

            if cursor.rowcount == 0:
                row = connection.execute(
                    f"SELECT status FROM {USER_TABLE} WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        f"User account was not found: {user_id}"
                    )
                raise PermissionError(
                    "Two-factor authentication is not enabled."
                )

            connection.execute(
                f"""
                UPDATE {TWO_FACTOR_RECOVERY_CODE_TABLE}
                SET
                    status = 'revoked',
                    updated_at = ?,
                    revoked_at = COALESCE(revoked_at, ?)
                WHERE user_id = ? AND status = 'active'
                """,
                (now_text, now_text, user_id),
            )
            self._revoke_two_factor_challenges_locked(
                connection,
                user_id=user_id,
                now_text=now_text,
            )
            revoked_sessions = self._revoke_user_sessions_locked(
                connection,
                user_id=user_id,
                now_text=now_text,
            )

        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("Disabled account could not be loaded.")
        return {
            "user": user,
            "revoked_sessions": revoked_sessions,
        }

    def replace_two_factor_recovery_codes(
        self,
        *,
        user_id: str,
        recovery_code_fingerprints: list[str],
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        fingerprints = self._validate_fingerprints(
            recovery_code_fingerprints
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT status, two_factor_enabled
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if (
                row is None
                or row["status"] != "active"
                or not bool(row["two_factor_enabled"])
            ):
                raise PermissionError(
                    "Two-factor authentication is not enabled."
                )

            self._replace_recovery_codes_locked(
                connection,
                user_id=user_id,
                fingerprints=fingerprints,
                now_text=now_text,
            )
            revoked_sessions = self._revoke_user_sessions_locked(
                connection,
                user_id=user_id,
                now_text=now_text,
            )

        return {
            "recovery_code_count": len(fingerprints),
            "revoked_sessions": revoked_sessions,
        }

    def count_active_two_factor_recovery_codes(
        self,
        user_id: str,
    ) -> int:
        user_id = self._validate_text(user_id, "User ID", 128)
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {TWO_FACTOR_RECOVERY_CODE_TABLE}
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def create_two_factor_challenge(
        self,
        *,
        user_id: str,
        token_fingerprint: str,
        expires_in_seconds: int,
        device_name: str | None = None,
        client_ref: str | None = None,
    ) -> dict[str, Any]:
        user_id = self._validate_text(user_id, "User ID", 128)
        token_fingerprint = self._validate_fingerprint(token_fingerprint)
        expires_in_seconds = self._validate_two_factor_challenge_expiry(
            expires_in_seconds
        )
        device_name = self._validate_optional_text(
            device_name,
            "Device name",
            200,
        )
        client_ref = self._validate_optional_text(
            client_ref,
            "Client reference",
            200,
        )
        challenge_id = uuid4().hex
        now = self._now()
        now_text = now.isoformat()
        expires_at = (
            now + timedelta(seconds=expires_in_seconds)
        ).isoformat()

        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT status, two_factor_enabled
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or not bool(row["two_factor_enabled"])
            ):
                raise PermissionError(
                    "Two-factor challenge cannot be created."
                )

            connection.execute(
                f"""
                INSERT INTO {TWO_FACTOR_CHALLENGE_TABLE} (
                    challenge_id,
                    user_id,
                    token_fingerprint,
                    device_name,
                    client_ref,
                    status,
                    created_at,
                    updated_at,
                    expires_at,
                    consumed_at,
                    revoked_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, NULL)
                """,
                (
                    challenge_id,
                    user_id,
                    token_fingerprint,
                    device_name,
                    client_ref,
                    now_text,
                    now_text,
                    expires_at,
                ),
            )
            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    failed_login_count = 0,
                    failed_login_window_started_at = NULL,
                    last_failed_login_at = NULL,
                    locked_until = NULL,
                    updated_at = ?
                WHERE user_id = ? AND status = 'active'
                """,
                (now_text, user_id),
            )

        created = self.get_two_factor_challenge(token_fingerprint)
        if created is None:
            raise RuntimeError("Two-factor challenge could not be loaded.")
        return created

    def get_two_factor_challenge(
        self,
        token_fingerprint: str,
    ) -> dict[str, Any] | None:
        token_fingerprint = self._validate_fingerprint(token_fingerprint)
        with self._connection() as connection:
            self._expire_two_factor_challenges_locked(connection)
            row = connection.execute(
                f"""
                SELECT *
                FROM {TWO_FACTOR_CHALLENGE_TABLE}
                WHERE token_fingerprint = ?
                """,
                (token_fingerprint,),
            ).fetchone()
        return self._two_factor_challenge_row_to_dict(row)

    def consume_two_factor_proof(
        self,
        *,
        user_id: str,
        totp_counter: int | None = None,
        recovery_code_fingerprint: str | None = None,
    ) -> bool:
        user_id = self._validate_text(user_id, "User ID", 128)
        counter, recovery = self._validate_two_factor_proof(
            totp_counter=totp_counter,
            recovery_code_fingerprint=recovery_code_fingerprint,
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT status, two_factor_enabled, two_factor_last_counter
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or not bool(row["two_factor_enabled"])
            ):
                return False

            if counter is not None:
                previous = row["two_factor_last_counter"]
                if previous is not None and counter <= int(previous):
                    return False
                connection.execute(
                    f"""
                    UPDATE {USER_TABLE}
                    SET
                        two_factor_last_counter = ?,
                        two_factor_updated_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (counter, now_text, now_text, user_id),
                )
            else:
                cursor = connection.execute(
                    f"""
                    UPDATE {TWO_FACTOR_RECOVERY_CODE_TABLE}
                    SET
                        status = 'consumed',
                        updated_at = ?,
                        consumed_at = ?
                    WHERE
                        user_id = ?
                        AND code_fingerprint = ?
                        AND status = 'active'
                    """,
                    (now_text, now_text, user_id, recovery),
                )
                if cursor.rowcount == 0:
                    return False

        return True

    def complete_two_factor_challenge(
        self,
        *,
        token_fingerprint: str,
        user_id: str,
        totp_counter: int | None = None,
        recovery_code_fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        token_fingerprint = self._validate_fingerprint(token_fingerprint)
        user_id = self._validate_text(user_id, "User ID", 128)
        counter, recovery = self._validate_two_factor_proof(
            totp_counter=totp_counter,
            recovery_code_fingerprint=recovery_code_fingerprint,
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._expire_two_factor_challenges_locked(connection)
            challenge = connection.execute(
                f"""
                SELECT *
                FROM {TWO_FACTOR_CHALLENGE_TABLE}
                WHERE
                    token_fingerprint = ?
                    AND user_id = ?
                    AND status = 'active'
                """,
                (token_fingerprint, user_id),
            ).fetchone()
            user = connection.execute(
                f"""
                SELECT status, two_factor_enabled, two_factor_last_counter
                FROM {USER_TABLE}
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if (
                challenge is None
                or user is None
                or user["status"] != "active"
                or not bool(user["two_factor_enabled"])
            ):
                return None

            if counter is not None:
                previous = user["two_factor_last_counter"]
                if previous is not None and counter <= int(previous):
                    return None
            else:
                recovery_row = connection.execute(
                    f"""
                    SELECT code_id
                    FROM {TWO_FACTOR_RECOVERY_CODE_TABLE}
                    WHERE
                        user_id = ?
                        AND code_fingerprint = ?
                        AND status = 'active'
                    """,
                    (user_id, recovery),
                ).fetchone()
                if recovery_row is None:
                    return None

            if counter is not None:
                connection.execute(
                    f"""
                    UPDATE {USER_TABLE}
                    SET
                        two_factor_last_counter = ?,
                        two_factor_updated_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (counter, now_text, now_text, user_id),
                )
            else:
                connection.execute(
                    f"""
                    UPDATE {TWO_FACTOR_RECOVERY_CODE_TABLE}
                    SET
                        status = 'consumed',
                        updated_at = ?,
                        consumed_at = ?
                    WHERE
                        user_id = ?
                        AND code_fingerprint = ?
                        AND status = 'active'
                    """,
                    (now_text, now_text, user_id, recovery),
                )

            cursor = connection.execute(
                f"""
                UPDATE {TWO_FACTOR_CHALLENGE_TABLE}
                SET
                    status = 'consumed',
                    updated_at = ?,
                    consumed_at = ?
                WHERE
                    challenge_id = ?
                    AND status = 'active'
                """,
                (now_text, now_text, challenge["challenge_id"]),
            )
            if cursor.rowcount == 0:
                return None

        result = dict(challenge)
        result["status"] = "consumed"
        result["updated_at"] = now_text
        result["consumed_at"] = now_text
        return self._two_factor_challenge_mapping_to_dict(result)

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
                SET
                    status = ?,
                    failed_login_count = 0,
                    failed_login_window_started_at = NULL,
                    last_failed_login_at = NULL,
                    locked_until = NULL,
                    updated_at = ?
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
                SET
                    last_login_at = ?,
                    failed_login_count = 0,
                    failed_login_window_started_at = NULL,
                    last_failed_login_at = NULL,
                    locked_until = NULL,
                    updated_at = ?
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


    def create_account_action_token(
        self,
        *,
        user_id: str,
        purpose: str,
        token: str,
        expires_in_seconds: int,
    ) -> dict[str, Any]:
        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )
        purpose = self._validate_account_action_token_purpose(
            purpose
        )
        token_fingerprint = fingerprint_account_action_token(
            token,
            purpose=purpose,
        )
        expires_in_seconds = (
            self._validate_account_action_token_expiry(
                expires_in_seconds
            )
        )
        user = self.get_user(user_id)

        if user is None:
            raise KeyError(
                f"User account was not found: {user_id}"
            )

        token_allowed = (
            user["status"] == "active"
            or (
                purpose == "password_reset"
                and user["status"] == "locked"
            )
        )

        if not token_allowed:
            raise PermissionError(
                "Account action tokens cannot be created "
                "for this user account."
            )

        token_id = uuid4().hex
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
                self._expire_account_action_tokens_locked(
                    connection
                )
                connection.execute(
                    f"""
                    UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                    SET
                        status = 'revoked',
                        updated_at = ?,
                        revoked_at = ?
                    WHERE
                        user_id = ?
                        AND purpose = ?
                        AND status = 'active'
                    """,
                    (
                        now_text,
                        now_text,
                        user_id,
                        purpose,
                    ),
                )
                connection.execute(
                    f"""
                    INSERT INTO {ACCOUNT_ACTION_TOKEN_TABLE} (
                        token_id,
                        user_id,
                        purpose,
                        token_fingerprint,
                        status,
                        created_at,
                        updated_at,
                        expires_at,
                        consumed_at,
                        revoked_at
                    )
                    VALUES (?, ?, ?, ?, 'active', ?, ?, ?, NULL, NULL)
                    """,
                    (
                        token_id,
                        user_id,
                        purpose,
                        token_fingerprint,
                        now_text,
                        now_text,
                        expires_at,
                    ),
                )

        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "This account action token is already registered."
            ) from exc

        created = self.get_account_action_token(
            token_id
        )

        if created is None:
            raise RuntimeError(
                "Created account action token could not be loaded."
            )

        return created

    def get_account_action_token(
        self,
        token_id: str,
    ) -> dict[str, Any] | None:
        token_id = self._validate_text(
            token_id,
            "Token ID",
            128,
        )

        with self._connection() as connection:
            self._expire_account_action_tokens_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT *
                FROM {ACCOUNT_ACTION_TOKEN_TABLE}
                WHERE token_id = ?
                """,
                (
                    token_id,
                ),
            ).fetchone()

        return self._account_action_token_row_to_dict(
            row
        )

    def revoke_account_action_token(
        self,
        token_id: str,
    ) -> dict[str, Any]:
        token_id = self._validate_text(
            token_id,
            "Token ID",
            128,
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            self._expire_account_action_tokens_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT status
                FROM {ACCOUNT_ACTION_TOKEN_TABLE}
                WHERE token_id = ?
                """,
                (
                    token_id,
                ),
            ).fetchone()

            if row is None:
                raise KeyError(
                    "Account action token was not found."
                )

            if row["status"] == "active":
                connection.execute(
                    f"""
                    UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                    SET
                        status = 'revoked',
                        updated_at = ?,
                        revoked_at = ?
                    WHERE token_id = ?
                    """,
                    (
                        now_text,
                        now_text,
                        token_id,
                    ),
                )

        updated = self.get_account_action_token(
            token_id
        )

        if updated is None:
            raise RuntimeError(
                "Revoked account action token could not be loaded."
            )

        return updated

    def confirm_email_verification_token(
        self,
        token: str,
    ) -> dict[str, Any] | None:
        fingerprint = fingerprint_account_action_token(
            token,
            purpose="email_verification",
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute(
                "BEGIN IMMEDIATE"
            )
            self._expire_account_action_tokens_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT
                    t.token_id,
                    t.user_id
                FROM {ACCOUNT_ACTION_TOKEN_TABLE} AS t
                INNER JOIN {USER_TABLE} AS u
                    ON u.user_id = t.user_id
                WHERE
                    t.token_fingerprint = ?
                    AND t.purpose = 'email_verification'
                    AND t.status = 'active'
                    AND u.status = 'active'
                """,
                (
                    fingerprint,
                ),
            ).fetchone()

            if row is None:
                return None

            cursor = connection.execute(
                f"""
                UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                SET
                    status = 'consumed',
                    updated_at = ?,
                    consumed_at = ?
                WHERE
                    token_id = ?
                    AND status = 'active'
                """,
                (
                    now_text,
                    now_text,
                    row["token_id"],
                ),
            )

            if cursor.rowcount != 1:
                return None

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    email_verified_at = COALESCE(
                        email_verified_at,
                        ?
                    ),
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    now_text,
                    now_text,
                    row["user_id"],
                ),
            )
            connection.execute(
                f"""
                UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                SET
                    status = 'revoked',
                    updated_at = ?,
                    revoked_at = ?
                WHERE
                    user_id = ?
                    AND purpose = 'email_verification'
                    AND status = 'active'
                """,
                (
                    now_text,
                    now_text,
                    row["user_id"],
                ),
            )
            user_id = row["user_id"]

        return self.get_user(
            user_id
        )

    def reset_password_with_token(
        self,
        *,
        token: str,
        new_password: str,
    ) -> dict[str, Any] | None:
        fingerprint = fingerprint_account_action_token(
            token,
            purpose="password_reset",
        )
        new_password_hash = hash_password(
            new_password
        )
        now_text = self._now().isoformat()

        with self._connection() as connection:
            connection.execute(
                "BEGIN IMMEDIATE"
            )
            self._expire_account_action_tokens_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT
                    t.token_id,
                    t.user_id
                FROM {ACCOUNT_ACTION_TOKEN_TABLE} AS t
                INNER JOIN {USER_TABLE} AS u
                    ON u.user_id = t.user_id
                WHERE
                    t.token_fingerprint = ?
                    AND t.purpose = 'password_reset'
                    AND t.status = 'active'
                    AND u.status IN ('active', 'locked')
                """,
                (
                    fingerprint,
                ),
            ).fetchone()

            if row is None:
                return None

            cursor = connection.execute(
                f"""
                UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                SET
                    status = 'consumed',
                    updated_at = ?,
                    consumed_at = ?
                WHERE
                    token_id = ?
                    AND status = 'active'
                """,
                (
                    now_text,
                    now_text,
                    row["token_id"],
                ),
            )

            if cursor.rowcount != 1:
                return None

            connection.execute(
                f"""
                UPDATE {USER_TABLE}
                SET
                    password_hash = ?,
                    status = 'active',
                    failed_login_count = 0,
                    failed_login_window_started_at = NULL,
                    last_failed_login_at = NULL,
                    locked_until = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    new_password_hash,
                    now_text,
                    row["user_id"],
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
                    row["user_id"],
                ),
            )
            connection.execute(
                f"""
                UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
                SET
                    status = 'revoked',
                    updated_at = ?,
                    revoked_at = ?
                WHERE
                    user_id = ?
                    AND purpose = 'password_reset'
                    AND status = 'active'
                """,
                (
                    now_text,
                    now_text,
                    row["user_id"],
                ),
            )
            user_id = row["user_id"]
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

    def count_account_action_tokens(
        self,
        *,
        user_id: str,
        purpose: str | None = None,
        status: str | None = None,
    ) -> int:
        user_id = self._validate_text(
            user_id,
            "User ID",
            128,
        )
        conditions = ["user_id = ?"]
        parameters: list[Any] = [user_id]

        if purpose is not None:
            purpose = (
                self._validate_account_action_token_purpose(
                    purpose
                )
            )
            conditions.append("purpose = ?")
            parameters.append(purpose)

        if status is not None:
            status = (
                self._validate_account_action_token_status(
                    status
                )
            )
            conditions.append("status = ?")
            parameters.append(status)

        with self._connection() as connection:
            self._expire_account_action_tokens_locked(
                connection
            )
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {ACCOUNT_ACTION_TOKEN_TABLE}
                WHERE {" AND ".join(conditions)}
                """,
                tuple(parameters),
            ).fetchone()

        return int(
            row["total"]
        )

    def delete_expired_account_action_tokens(
        self,
        *,
        limit: int = 1000,
    ) -> int:
        limit = self._validate_limit(
            limit
        )

        with self._connection() as connection:
            self._expire_account_action_tokens_locked(
                connection
            )
            cursor = connection.execute(
                f"""
                DELETE FROM {ACCOUNT_ACTION_TOKEN_TABLE}
                WHERE sequence_id IN (
                    SELECT sequence_id
                    FROM {ACCOUNT_ACTION_TOKEN_TABLE}
                    WHERE status = 'expired'
                    ORDER BY sequence_id ASC
                    LIMIT ?
                )
                """,
                (
                    limit,
                ),
            )

        return int(
            cursor.rowcount
        )

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
            connection.execute(
                f"DELETE FROM {TWO_FACTOR_RECOVERY_CODE_TABLE}"
            )
            connection.execute(
                f"DELETE FROM {TWO_FACTOR_CHALLENGE_TABLE}"
            )
            connection.execute(
                f"DELETE FROM {ACCOUNT_ACTION_TOKEN_TABLE}"
            )
            connection.execute(f"DELETE FROM {SESSION_TABLE}")
            connection.execute(f"DELETE FROM {USER_ROLE_TABLE}")
            connection.execute(f"DELETE FROM {USER_TABLE}")


    def _get_user_roles_locked(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            f"""
            SELECT role
            FROM {USER_ROLE_TABLE}
            WHERE user_id = ?
            ORDER BY role ASC
            """,
            (user_id,),
        ).fetchall()

        return tuple(
            row["role"]
            for row in rows
            if row["role"] in ACCOUNT_ROLES
        )

    def _count_active_admins_locked(
        self,
        connection: sqlite3.Connection,
    ) -> int:
        row = connection.execute(
            f"""
            SELECT COUNT(DISTINCT u.user_id) AS total
            FROM {USER_TABLE} u
            JOIN {USER_ROLE_TABLE} r
                ON r.user_id = u.user_id
            WHERE u.status = 'active'
            AND r.role = ?
            """,
            (ROLE_ADMIN,),
        ).fetchone()

        return int(row["total"])


    def _expire_two_factor_challenges_locked(
        self,
        connection: sqlite3.Connection,
    ) -> int:
        now_text = self._now().isoformat()
        cursor = connection.execute(
            f"""
            UPDATE {TWO_FACTOR_CHALLENGE_TABLE}
            SET status = 'expired', updated_at = ?
            WHERE status = 'active' AND expires_at <= ?
            """,
            (now_text, now_text),
        )
        return int(cursor.rowcount)

    def _revoke_two_factor_challenges_locked(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        now_text: str,
    ) -> int:
        cursor = connection.execute(
            f"""
            UPDATE {TWO_FACTOR_CHALLENGE_TABLE}
            SET
                status = 'revoked',
                updated_at = ?,
                revoked_at = COALESCE(revoked_at, ?)
            WHERE user_id = ? AND status = 'active'
            """,
            (now_text, now_text, user_id),
        )
        return int(cursor.rowcount)

    def _revoke_user_sessions_locked(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        now_text: str,
    ) -> int:
        cursor = connection.execute(
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
        return int(cursor.rowcount)

    def _replace_recovery_codes_locked(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        fingerprints: list[str],
        now_text: str,
    ) -> None:
        connection.execute(
            f"""
            UPDATE {TWO_FACTOR_RECOVERY_CODE_TABLE}
            SET
                status = 'revoked',
                updated_at = ?,
                revoked_at = COALESCE(revoked_at, ?)
            WHERE user_id = ? AND status = 'active'
            """,
            (now_text, now_text, user_id),
        )
        connection.executemany(
            f"""
            INSERT INTO {TWO_FACTOR_RECOVERY_CODE_TABLE} (
                code_id,
                user_id,
                code_fingerprint,
                status,
                created_at,
                updated_at,
                consumed_at,
                revoked_at
            ) VALUES (?, ?, ?, 'active', ?, ?, NULL, NULL)
            """,
            [
                (uuid4().hex, user_id, value, now_text, now_text)
                for value in fingerprints
            ],
        )

    def _unlock_expired_user_locks_locked(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str | None = None,
        email: str | None = None,
    ) -> int:
        conditions = [
            "status = 'locked'",
            "locked_until IS NOT NULL",
            "locked_until <= ?",
        ]
        parameters: list[Any] = [
            self._now().isoformat()
        ]

        if user_id is not None:
            conditions.append(
                "user_id = ?"
            )
            parameters.append(
                user_id
            )

        if email is not None:
            conditions.append(
                "email = ?"
            )
            parameters.append(
                email
            )

        now_text = parameters[0]
        cursor = connection.execute(
            f"""
            UPDATE {USER_TABLE}
            SET
                status = 'active',
                failed_login_count = 0,
                failed_login_window_started_at = NULL,
                last_failed_login_at = NULL,
                locked_until = NULL,
                updated_at = ?
            WHERE {" AND ".join(conditions)}
            """,
            tuple(
                [now_text]
                + parameters
            ),
        )
        return int(
            cursor.rowcount
        )

    def _expire_account_action_tokens_locked(
        self,
        connection: sqlite3.Connection,
    ) -> int:
        now_text = self._now().isoformat()
        cursor = connection.execute(
            f"""
            UPDATE {ACCOUNT_ACTION_TOKEN_TABLE}
            SET
                status = 'expired',
                updated_at = ?
            WHERE
                status = 'active'
                AND expires_at <= ?
            """,
            (
                now_text,
                now_text,
            ),
        )
        return int(
            cursor.rowcount
        )

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

    @staticmethod
    def _ensure_column_locked(
        connection: sqlite3.Connection,
        *,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }

        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} "
                f"{column_definition}"
            )

    def _now(self) -> datetime:
        current = self._clock()

        if not isinstance(current, datetime):
            raise TypeError("Authentication clock must return datetime.")

        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        return current.astimezone(timezone.utc)

    @staticmethod
    def _user_row_to_dict(
        row: sqlite3.Row | None,
        *,
        roles: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "status": row["status"],
            "roles": list(roles),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
            "email_verified_at": row["email_verified_at"],
            "email_verified": (
                row["email_verified_at"] is not None
            ),
            "two_factor_enabled": bool(
                row["two_factor_enabled"]
            ),
            "two_factor_confirmed_at": (
                row["two_factor_confirmed_at"]
            ),
            "two_factor_updated_at": (
                row["two_factor_updated_at"]
            ),
        }

    @staticmethod
    def _account_action_token_row_to_dict(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        fingerprint = row["token_fingerprint"]

        return {
            "token_id": row["token_id"],
            "user_id": row["user_id"],
            "purpose": row["purpose"],
            "token_ref": fingerprint[:12],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
            "consumed_at": row["consumed_at"],
            "revoked_at": row["revoked_at"],
        }

    @staticmethod
    def _two_factor_challenge_mapping_to_dict(
        row: Any,
    ) -> dict[str, Any]:
        fingerprint = row["token_fingerprint"]
        return {
            "challenge_id": row["challenge_id"],
            "user_id": row["user_id"],
            "token_ref": fingerprint[:12],
            "device_name": row["device_name"],
            "client_ref": row["client_ref"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
            "consumed_at": row["consumed_at"],
            "revoked_at": row["revoked_at"],
        }

    @classmethod
    def _two_factor_challenge_row_to_dict(
        cls,
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        return cls._two_factor_challenge_mapping_to_dict(row)

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

    @classmethod
    def _validate_account_action_token_purpose(
        cls,
        purpose: str,
    ) -> str:
        purpose = cls._validate_text(
            purpose,
            "Account action token purpose",
            64,
        ).lower()

        if purpose not in ACCOUNT_ACTION_TOKEN_PURPOSES:
            raise ValueError(
                "Unsupported account action token purpose: "
                f"{purpose}"
            )

        return purpose

    @classmethod
    def _validate_account_action_token_status(
        cls,
        status: str,
    ) -> str:
        status = cls._validate_text(
            status,
            "Account action token status",
            32,
        ).lower()

        if status not in ACCOUNT_ACTION_TOKEN_STATUSES:
            raise ValueError(
                "Unsupported account action token status: "
                f"{status}"
            )

        return status

    @staticmethod
    def _validate_account_action_token_expiry(
        expires_in_seconds: int,
    ) -> int:
        if isinstance(
            expires_in_seconds,
            bool,
        ) or not isinstance(
            expires_in_seconds,
            int,
        ):
            raise TypeError(
                "Account action token expiry must be an integer."
            )

        if not (
            ACCOUNT_ACTION_TOKEN_MINIMUM_SECONDS
            <= expires_in_seconds
            <= ACCOUNT_ACTION_TOKEN_MAXIMUM_SECONDS
        ):
            raise ValueError(
                "Account action token expiry must be between "
                f"{ACCOUNT_ACTION_TOKEN_MINIMUM_SECONDS} and "
                f"{ACCOUNT_ACTION_TOKEN_MAXIMUM_SECONDS} seconds."
            )

        return expires_in_seconds


    @staticmethod
    def _validate_login_protection_parameters(
        *,
        failure_limit: int,
        failure_window_seconds: int,
        lockout_seconds: int,
    ) -> None:
        values = (
            (
                failure_limit,
                "Failure limit",
                2,
                100,
            ),
            (
                failure_window_seconds,
                "Failure window",
                60,
                86400,
            ),
            (
                lockout_seconds,
                "Lockout duration",
                60,
                604800,
            ),
        )

        for value, label, minimum, maximum in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
            ):
                raise TypeError(
                    f"{label} must be an integer."
                )

            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{label} must be between "
                    f"{minimum} and {maximum}."
                )

    @staticmethod
    def _validate_counter(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("TOTP counter must be an integer.")
        if value < 0:
            raise ValueError("TOTP counter cannot be negative.")
        return value

    @classmethod
    def _validate_fingerprints(cls, values: list[str]) -> list[str]:
        if not isinstance(values, list):
            raise TypeError("Recovery-code fingerprints must be a list.")
        normalized = [cls._validate_fingerprint(value) for value in values]
        if not 5 <= len(normalized) <= 20:
            raise ValueError(
                "Recovery-code fingerprints must contain 5 to 20 values."
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("Recovery-code fingerprints must be unique.")
        return normalized

    @staticmethod
    def _validate_fingerprint(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("Fingerprint must be text.")
        normalized = value.strip().lower()
        if (
            len(normalized) != 64
            or any(character not in "0123456789abcdef" for character in normalized)
        ):
            raise ValueError("Fingerprint is invalid.")
        return normalized

    @classmethod
    def _validate_two_factor_proof(
        cls,
        *,
        totp_counter: int | None,
        recovery_code_fingerprint: str | None,
    ) -> tuple[int | None, str | None]:
        supplied = int(totp_counter is not None) + int(
            recovery_code_fingerprint is not None
        )
        if supplied != 1:
            raise ValueError(
                "Exactly one two-factor proof must be supplied."
            )
        if totp_counter is not None:
            return cls._validate_counter(totp_counter), None
        return None, cls._validate_fingerprint(
            str(recovery_code_fingerprint)
        )

    @staticmethod
    def _validate_two_factor_challenge_expiry(
        expires_in_seconds: int,
    ) -> int:
        if (
            isinstance(expires_in_seconds, bool)
            or not isinstance(expires_in_seconds, int)
        ):
            raise TypeError("Two-factor challenge expiry must be an integer.")
        if not (
            TWO_FACTOR_CHALLENGE_MINIMUM_SECONDS
            <= expires_in_seconds
            <= TWO_FACTOR_CHALLENGE_MAXIMUM_SECONDS
        ):
            raise ValueError(
                "Two-factor challenge expiry must be between "
                f"{TWO_FACTOR_CHALLENGE_MINIMUM_SECONDS} and "
                f"{TWO_FACTOR_CHALLENGE_MAXIMUM_SECONDS} seconds."
            )
        return expires_in_seconds

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
    "ACCOUNT_ACTION_TOKEN_PURPOSES",
    "ACCOUNT_ACTION_TOKEN_STATUSES",
    "ACCOUNT_ACTION_TOKEN_TABLE",
    "PASSWORD_MAXIMUM_LENGTH",
    "PASSWORD_MINIMUM_LENGTH",
    "REFRESH_TOKEN_MAXIMUM_LENGTH",
    "REFRESH_TOKEN_MINIMUM_LENGTH",
    "SESSION_STATUSES",
    "SESSION_TABLE",
    "TWO_FACTOR_CHALLENGE_TABLE",
    "TWO_FACTOR_RECOVERY_CODE_TABLE",
    "SQLiteAuthenticationStore",
    "USER_ROLE_TABLE",
    "USER_STATUSES",
    "USER_TABLE",
    "authentication_store",
    "fingerprint_account_action_token",
    "fingerprint_refresh_token",
    "hash_password",
    "normalize_email",
    "verify_password_hash",
]