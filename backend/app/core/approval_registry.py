"""
Secure approval registry for sensitive Mama AI tasks.

Approval tokens are:
- Cryptographically random
- Stored only as SHA-256 hashes
- Bound to one task and one owner
- Time limited
- Valid for one use only

Persistence is optional and disabled by default.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from app.core.task import RiskLevel


class ApprovalStateStore(Protocol):
    """Storage interface required by ApprovalRegistry."""

    def save_approval(self, record: Any) -> None:
        ...

    def list_approvals(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(
    value: datetime | str,
    field_name: str,
) -> datetime:
    if isinstance(value, datetime):
        parsed = value

    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be a valid ISO datetime."
            ) from exc

    else:
        raise TypeError(
            f"{field_name} must be a datetime or ISO text."
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    task_id: str
    owner_id: str
    command: str
    risk_level: RiskLevel
    reasons: list[str]
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    consumed_at: datetime | None = None
    token_hash: str | None = field(
        default=None,
        repr=False,
    )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ApprovalRecord":
        if not isinstance(data, dict):
            raise TypeError(
                "Persisted approval data must be a dictionary."
            )

        decided_at = data.get("decided_at")
        consumed_at = data.get("consumed_at")

        return cls(
            approval_id=str(data["approval_id"]),
            task_id=str(data["task_id"]),
            owner_id=str(data["owner_id"]),
            command=str(data["command"]),
            risk_level=RiskLevel(data["risk_level"]),
            reasons=[
                str(reason)
                for reason in (data.get("reasons") or [])
            ],
            status=ApprovalStatus(data["status"]),
            created_at=_parse_datetime(
                data["created_at"],
                "Created at",
            ),
            expires_at=_parse_datetime(
                data["expires_at"],
                "Expires at",
            ),
            decided_at=(
                _parse_datetime(
                    decided_at,
                    "Decided at",
                )
                if decided_at is not None
                else None
            ),
            consumed_at=(
                _parse_datetime(
                    consumed_at,
                    "Consumed at",
                )
                if consumed_at is not None
                else None
            ),
            token_hash=(
                str(data["token_hash"])
                if data.get("token_hash") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "owner_id": self.owner_id,
            "command": self.command,
            "risk_level": self.risk_level.value,
            "reasons": list(self.reasons),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decided_at": (
                self.decided_at.isoformat()
                if self.decided_at
                else None
            ),
            "consumed_at": (
                self.consumed_at.isoformat()
                if self.consumed_at
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    approval_id: str
    task_id: str
    owner_id: str
    token: str
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "owner_id": self.owner_id,
            "token": self.token,
            "expires_at": self.expires_at.isoformat(),
        }


class ApprovalRegistry:
    """
    Thread-safe approval request and token registry.

    Persistence must be explicitly enabled so imports and unit tests
    do not write to the production database.
    """

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = RLock()
        self._clock = clock or utc_datetime
        self._store: ApprovalStateStore | None = None
        self._persistence_enabled = False

    @property
    def persistence_enabled(self) -> bool:
        return self._persistence_enabled

    def enable_persistence(
        self,
        store: ApprovalStateStore,
        *,
        restore: bool = True,
    ) -> int:
        """
        Attach persistent approval storage.

        Returns the number of approval records restored.
        """

        if store is None:
            raise TypeError(
                "An approval persistence store is required."
            )

        if not callable(
            getattr(store, "save_approval", None)
        ):
            raise TypeError(
                "Approval store must provide save_approval()."
            )

        if not callable(
            getattr(store, "list_approvals", None)
        ):
            raise TypeError(
                "Approval store must provide list_approvals()."
            )

        with self._lock:
            self._store = store
            self._persistence_enabled = True

        if restore:
            return self.restore()

        return 0

    def disable_persistence(self) -> None:
        """
        Stop future writes without clearing memory or database rows.
        """

        with self._lock:
            self._persistence_enabled = False
            self._store = None

    def restore(self) -> int:
        """
        Restore approval records from persistent storage.

        Pending and approved records that passed their expiration time
        are restored as expired.
        """

        store = self._require_store()
        rows = store.list_approvals(limit=1000)

        restored: dict[str, ApprovalRecord] = {}

        for data in rows:
            record = ApprovalRecord.from_dict(data)

            changed = self._refresh_expiry_locked(record)

            if changed:
                store.save_approval(record)

            restored[record.approval_id] = record

        with self._lock:
            self._records = restored

        return len(restored)

    def create(
        self,
        *,
        task_id: str,
        owner_id: str,
        command: str,
        risk_level: RiskLevel,
        reasons: list[str] | None = None,
        ttl_seconds: int = 300,
    ) -> ApprovalRecord:
        task_id = self._validate_text(task_id, "Task ID")
        owner_id = self._validate_text(owner_id, "Owner ID")
        command = self._validate_text(command, "Command")

        if not isinstance(ttl_seconds, int):
            raise TypeError(
                "Approval lifetime must be an integer."
            )

        if ttl_seconds < 1 or ttl_seconds > 1800:
            raise ValueError(
                "Approval lifetime must be between 1 and "
                "1800 seconds."
            )

        risk_level = RiskLevel(risk_level)
        now = self._now()

        record = ApprovalRecord(
            approval_id=uuid4().hex,
            task_id=task_id,
            owner_id=owner_id,
            command=command,
            risk_level=risk_level,
            reasons=[
                str(reason).strip()
                for reason in (reasons or [])
                if str(reason).strip()
            ],
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=(
                now + timedelta(seconds=ttl_seconds)
            ),
        )

        with self._lock:
            self._records[record.approval_id] = record

            try:
                self._persist_locked(record)
            except Exception:
                self._records.pop(
                    record.approval_id,
                    None,
                )
                raise

        return deepcopy(record)

    def approve(
        self,
        approval_id: str,
        *,
        owner_id: str,
    ) -> ApprovalGrant:
        approval_id = self._validate_text(
            approval_id,
            "Approval ID",
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
        )

        with self._lock:
            record = self._require_locked(approval_id)

            self._refresh_and_persist_locked(record)
            self._verify_owner(record, owner_id)

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError(
                    "The approval request has expired."
                )

            if record.status != ApprovalStatus.PENDING:
                raise ValueError(
                    "Approval cannot be granted from status "
                    f"{record.status.value}."
                )

            previous = deepcopy(record)
            token = secrets.token_urlsafe(32)

            try:
                record.token_hash = self._hash_token(token)
                record.status = ApprovalStatus.APPROVED
                record.decided_at = self._now()

                self._persist_locked(record)

            except Exception:
                self._records[approval_id] = previous
                raise

            return ApprovalGrant(
                approval_id=record.approval_id,
                task_id=record.task_id,
                owner_id=record.owner_id,
                token=token,
                expires_at=record.expires_at,
            )

    def reject(
        self,
        approval_id: str,
        *,
        owner_id: str,
    ) -> ApprovalRecord:
        approval_id = self._validate_text(
            approval_id,
            "Approval ID",
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
        )

        with self._lock:
            record = self._require_locked(approval_id)

            self._refresh_and_persist_locked(record)
            self._verify_owner(record, owner_id)

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError(
                    "The approval request has expired."
                )

            if record.status != ApprovalStatus.PENDING:
                raise ValueError(
                    "Approval cannot be rejected from status "
                    f"{record.status.value}."
                )

            previous = deepcopy(record)

            try:
                record.status = ApprovalStatus.REJECTED
                record.decided_at = self._now()
                record.token_hash = None

                self._persist_locked(record)

            except Exception:
                self._records[approval_id] = previous
                raise

            return deepcopy(record)

    def consume(
        self,
        approval_id: str,
        *,
        task_id: str,
        owner_id: str,
        token: str,
    ) -> ApprovalRecord:
        approval_id = self._validate_text(
            approval_id,
            "Approval ID",
        )
        task_id = self._validate_text(
            task_id,
            "Task ID",
        )
        owner_id = self._validate_text(
            owner_id,
            "Owner ID",
        )
        token = self._validate_text(
            token,
            "Approval token",
        )

        with self._lock:
            record = self._require_locked(approval_id)

            self._refresh_and_persist_locked(record)
            self._verify_owner(record, owner_id)

            if record.task_id != task_id:
                raise PermissionError(
                    "The approval token does not belong "
                    "to this task."
                )

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError(
                    "The approval token has expired."
                )

            if record.status == ApprovalStatus.CONSUMED:
                raise PermissionError(
                    "The approval token has already been used."
                )

            if record.status != ApprovalStatus.APPROVED:
                raise PermissionError(
                    "The task has not been approved."
                )

            supplied_hash = self._hash_token(token)
            stored_hash = record.token_hash or ""

            if not secrets.compare_digest(
                supplied_hash,
                stored_hash,
            ):
                raise PermissionError(
                    "Invalid approval token."
                )

            previous = deepcopy(record)

            try:
                record.status = ApprovalStatus.CONSUMED
                record.consumed_at = self._now()
                record.token_hash = None

                self._persist_locked(record)

            except Exception:
                self._records[approval_id] = previous
                raise

            return deepcopy(record)

    def get(
        self,
        approval_id: str,
    ) -> ApprovalRecord | None:
        approval_id = self._validate_text(
            approval_id,
            "Approval ID",
        )

        with self._lock:
            record = self._records.get(approval_id)

            if record is None:
                return None

            self._refresh_and_persist_locked(record)

            return deepcopy(record)

    def require(
        self,
        approval_id: str,
    ) -> ApprovalRecord:
        record = self.get(approval_id)

        if record is None:
            raise KeyError(
                "Approval request was not found: "
                f"{approval_id}"
            )

        return record

    def list(
        self,
        *,
        status: ApprovalStatus | str | None = None,
        owner_id: str | None = None,
    ) -> list[ApprovalRecord]:
        required_status = (
            ApprovalStatus(status)
            if status is not None
            else None
        )

        if owner_id is not None:
            owner_id = self._validate_text(
                owner_id,
                "Owner ID",
            )

        with self._lock:
            for record in self._records.values():
                self._refresh_and_persist_locked(record)

            records = list(self._records.values())

            if required_status is not None:
                records = [
                    record
                    for record in records
                    if record.status == required_status
                ]

            if owner_id is not None:
                records = [
                    record
                    for record in records
                    if record.owner_id == owner_id
                ]

            records.sort(
                key=lambda record: record.created_at,
                reverse=True,
            )

            return deepcopy(records)

    def clear(self) -> None:
        """
        Clear in-memory approval records only.

        Persistent database rows are intentionally preserved.
        """

        with self._lock:
            self._records.clear()

    def _refresh_and_persist_locked(
        self,
        record: ApprovalRecord,
    ) -> None:
        previous = deepcopy(record)

        try:
            changed = self._refresh_expiry_locked(record)

            if changed:
                self._persist_locked(record)

        except Exception:
            self._records[record.approval_id] = previous
            raise

    def _refresh_expiry_locked(
        self,
        record: ApprovalRecord,
    ) -> bool:
        if (
            record.status
            in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            }
            and self._now() >= record.expires_at
        ):
            record.status = ApprovalStatus.EXPIRED
            record.token_hash = None
            return True

        return False

    def _persist_locked(
        self,
        record: ApprovalRecord,
    ) -> None:
        if not self._persistence_enabled:
            return

        store = self._require_store()
        store.save_approval(record)

    def _require_store(self) -> ApprovalStateStore:
        with self._lock:
            if (
                not self._persistence_enabled
                or self._store is None
            ):
                raise RuntimeError(
                    "Approval persistence has not been enabled."
                )

            return self._store

    def _require_locked(
        self,
        approval_id: str,
    ) -> ApprovalRecord:
        record = self._records.get(approval_id)

        if record is None:
            raise KeyError(
                "Approval request was not found: "
                f"{approval_id}"
            )

        return record

    @staticmethod
    def _verify_owner(
        record: ApprovalRecord,
        owner_id: str,
    ) -> None:
        if record.owner_id != owner_id:
            raise PermissionError(
                "This approval request belongs to "
                "another owner."
            )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    def _now(self) -> datetime:
        current = self._clock()

        if not isinstance(current, datetime):
            raise TypeError(
                "Approval registry clock must return datetime."
            )

        if current.tzinfo is None:
            current = current.replace(
                tzinfo=timezone.utc
            )

        return current.astimezone(timezone.utc)

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


approval_registry = ApprovalRegistry()


__all__ = [
    "ApprovalGrant",
    "ApprovalRecord",
    "ApprovalRegistry",
    "ApprovalStateStore",
    "ApprovalStatus",
    "approval_registry",
]