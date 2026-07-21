"""
Secure approval registry for sensitive Mama AI tasks.

Approval tokens are:
- Cryptographically random
- Stored only as SHA-256 hashes
- Bound to one task and one owner
- Time limited
- Valid for one use only
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
from typing import Any
from uuid import uuid4

from app.core.task import RiskLevel


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


def utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


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
    """Thread-safe approval request and token registry."""

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = RLock()
        self._clock = clock or utc_datetime

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
            raise TypeError("Approval lifetime must be an integer.")

        if ttl_seconds < 1 or ttl_seconds > 1800:
            raise ValueError(
                "Approval lifetime must be between 1 and 1800 seconds."
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
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

        with self._lock:
            self._records[record.approval_id] = record

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
        owner_id = self._validate_text(owner_id, "Owner ID")

        with self._lock:
            record = self._require_locked(approval_id)
            self._refresh_expiry_locked(record)

            self._verify_owner(record, owner_id)

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError("The approval request has expired.")

            if record.status != ApprovalStatus.PENDING:
                raise ValueError(
                    f"Approval cannot be granted from status "
                    f"{record.status.value}."
                )

            token = secrets.token_urlsafe(32)

            record.token_hash = self._hash_token(token)
            record.status = ApprovalStatus.APPROVED
            record.decided_at = self._now()

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
        owner_id = self._validate_text(owner_id, "Owner ID")

        with self._lock:
            record = self._require_locked(approval_id)
            self._refresh_expiry_locked(record)

            self._verify_owner(record, owner_id)

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError("The approval request has expired.")

            if record.status != ApprovalStatus.PENDING:
                raise ValueError(
                    f"Approval cannot be rejected from status "
                    f"{record.status.value}."
                )

            record.status = ApprovalStatus.REJECTED
            record.decided_at = self._now()
            record.token_hash = None

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
        task_id = self._validate_text(task_id, "Task ID")
        owner_id = self._validate_text(owner_id, "Owner ID")
        token = self._validate_text(token, "Approval token")

        with self._lock:
            record = self._require_locked(approval_id)
            self._refresh_expiry_locked(record)

            self._verify_owner(record, owner_id)

            if record.task_id != task_id:
                raise PermissionError(
                    "The approval token does not belong to this task."
                )

            if record.status == ApprovalStatus.EXPIRED:
                raise TimeoutError("The approval token has expired.")

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
                raise PermissionError("Invalid approval token.")

            record.status = ApprovalStatus.CONSUMED
            record.consumed_at = self._now()
            record.token_hash = None

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

            self._refresh_expiry_locked(record)
            return deepcopy(record)

    def require(
        self,
        approval_id: str,
    ) -> ApprovalRecord:
        record = self.get(approval_id)

        if record is None:
            raise KeyError(
                f"Approval request was not found: {approval_id}"
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
            owner_id = self._validate_text(owner_id, "Owner ID")

        with self._lock:
            for record in self._records.values():
                self._refresh_expiry_locked(record)

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
        with self._lock:
            self._records.clear()

    def _require_locked(
        self,
        approval_id: str,
    ) -> ApprovalRecord:
        record = self._records.get(approval_id)

        if record is None:
            raise KeyError(
                f"Approval request was not found: {approval_id}"
            )

        return record

    def _refresh_expiry_locked(
        self,
        record: ApprovalRecord,
    ) -> None:
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

    @staticmethod
    def _verify_owner(
        record: ApprovalRecord,
        owner_id: str,
    ) -> None:
        if record.owner_id != owner_id:
            raise PermissionError(
                "This approval request belongs to another owner."
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
            current = current.replace(tzinfo=timezone.utc)

        return current.astimezone(timezone.utc)

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


approval_registry = ApprovalRegistry()


__all__ = [
    "ApprovalGrant",
    "ApprovalRecord",
    "ApprovalRegistry",
    "ApprovalStatus",
    "approval_registry",
]