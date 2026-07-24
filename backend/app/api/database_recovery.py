"""Privileged database migration, backup, and recovery diagnostics API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.auth import (
    AuthenticatedPrincipal,
    require_database_recovery_administrator,
    require_database_recovery_reader,
)
from app.database.migrations import migration_manager
from app.database.recovery import (
    BackupIntegrityError,
    BackupNotFoundError,
    DatabaseRecoveryError,
    RecoveryBusyError,
    backup_manager,
)
from app.database.recovery_scheduler import database_recovery_scheduler
from app.database.security_event_db import record_security_event_safely


router = APIRouter(prefix="/admin/database", tags=["Database Recovery"])


class CreateBackupRequest(BaseModel):
    reason: str = "manual_api"


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BackupNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RecoveryBusyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BackupIntegrityError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (TypeError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DatabaseRecoveryError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail="Database recovery action failed.")


def _record_action(
    *,
    principal: AuthenticatedPrincipal,
    request: Request,
    action: str,
    metadata: dict[str, Any],
) -> None:
    record_security_event_safely(
        event_type="account_administration",
        severity="warning",
        owner_id=principal.owner_id,
        request_method=request.method,
        request_path=request.url.path,
        status_code=200,
        message="Privileged database recovery action completed.",
        metadata={
            "scope": "database_recovery",
            "action": action,
            **metadata,
        },
    )


@router.get("/status")
def database_recovery_status(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_database_recovery_reader),
    ],
) -> dict[str, Any]:
    try:
        return {
            "success": True,
            "migration": migration_manager.status(),
            "recovery": backup_manager.status(),
            "scheduler": database_recovery_scheduler.status(),
        }
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/backups")
def list_database_backups(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_database_recovery_reader),
    ],
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        backups = backup_manager.list_backups(limit=limit)
    except Exception as exc:
        raise _map_error(exc) from exc
    return {"success": True, "backups": backups, "count": len(backups)}


@router.post("/backups")
def create_database_backup(
    payload: CreateBackupRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_database_recovery_administrator),
    ],
) -> dict[str, Any]:
    try:
        backup = backup_manager.create_backup(
            reason=payload.reason,
            metadata={"initiated_by": "api"},
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    _record_action(
        principal=principal,
        request=request,
        action="database_backup_created",
        metadata={"backup_id": backup["backup_id"], "filename": backup["filename"]},
    )
    return {"success": True, "backup": backup}


@router.post("/backups/prune")
def prune_database_backups(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_database_recovery_administrator),
    ],
    keep: int | None = Query(default=None, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        result = backup_manager.prune_backups(keep=keep)
    except Exception as exc:
        raise _map_error(exc) from exc
    _record_action(
        principal=principal,
        request=request,
        action="database_backups_pruned",
        metadata={"removed_count": len(result["removed"]), "kept": result["kept"]},
    )
    return {"success": True, **result}


@router.post("/backups/{filename}/verify")
def verify_database_backup(
    filename: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_database_recovery_reader),
    ],
) -> dict[str, Any]:
    try:
        verification = backup_manager.verify_backup(filename)
    except Exception as exc:
        raise _map_error(exc) from exc
    _record_action(
        principal=principal,
        request=request,
        action="database_backup_verified",
        metadata={"filename": verification["filename"]},
    )
    return {"success": True, "verification": verification}


__all__ = [
    "CreateBackupRequest",
    "create_database_backup",
    "database_recovery_status",
    "list_database_backups",
    "prune_database_backups",
    "router",
    "verify_database_backup",
]
