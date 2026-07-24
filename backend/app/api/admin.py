"""Administrative account and role-management API for Mama AI."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import (
    AuthenticatedPrincipal,
    require_account_administrator,
    require_account_reader,
)
from app.core.auth_service import (
    AccountAdministrationConflictError,
    AccountAuthorizationError,
    AccountNotFoundError,
    InvalidAccountRoleError,
    authentication_service,
)
from app.core.rbac import ACCOUNT_ROLES
from app.core.device_security_service import (
    device_security_service,
)
from app.database.auth_db import USER_STATUSES
from app.database.security_event_db import record_security_event_safely


router = APIRouter(
    prefix="/auth/admin",
    tags=["Account Administration"],
)


def _target_reference(user_id: str) -> str:
    digest = hashlib.sha256(
        (
            "mama-ai:admin-account-target:"
            + str(user_id).strip()
        ).encode("utf-8")
    ).hexdigest()
    return "account:" + digest[:12]


def _record_administrative_action(
    *,
    principal: AuthenticatedPrincipal,
    action: str,
    target_user_id: str,
    changed: bool = True,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_security_event_safely(
        event_type="account_administration",
        severity="warning",
        owner_id=principal.owner_id,
        request_method="POST",
        request_path="/auth/admin/accounts",
        status_code=status.HTTP_200_OK,
        message="Administrative account action completed.",
        metadata={
            "action": action,
            "target_reference": _target_reference(
                target_user_id
            ),
            "changed": bool(changed),
            "actor_roles": list(principal.roles),
            **(metadata or {}),
        },
    )


def _map_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AccountNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    if isinstance(
        exc,
        AccountAdministrationConflictError,
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    if isinstance(exc, AccountAuthorizationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    if isinstance(exc, InvalidAccountRoleError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if isinstance(exc, (TypeError, ValueError)):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Account administration failed.",
    )


@router.get("/accounts")
def list_accounts(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_reader),
    ],
    account_status: str | None = Query(
        default=None,
        alias="status",
    ),
    role: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    if (
        account_status is not None
        and account_status not in USER_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Account status must be one of: "
                + ", ".join(sorted(USER_STATUSES))
                + "."
            ),
        )

    if role is not None and role.strip().lower() not in ACCOUNT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Account role must be one of: "
                + ", ".join(sorted(ACCOUNT_ROLES))
                + "."
            ),
        )

    try:
        result = authentication_service.list_accounts(
            actor_roles=principal.roles,
            status=account_status,
            role=role,
            limit=limit,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    return {
        "success": True,
        **result,
    }


@router.get("/accounts/{user_id}")
def get_account(
    user_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_reader),
    ],
) -> dict[str, Any]:
    try:
        user = authentication_service.get_account(
            actor_roles=principal.roles,
            user_id=user_id,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    return {
        "success": True,
        "user": user,
    }


@router.post("/accounts/{user_id}/enable")
def enable_account(
    user_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_administrator),
    ],
) -> dict[str, Any]:
    try:
        result = authentication_service.enable_account(
            actor_user_id=principal.owner_id,
            actor_roles=principal.roles,
            user_id=user_id,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    _record_administrative_action(
        principal=principal,
        action="account_enabled",
        target_user_id=user_id,
        metadata={
            "previous_status": result["previous_status"],
        },
    )
    return {"success": True, **result}


@router.post("/accounts/{user_id}/disable")
def disable_account(
    user_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_administrator),
    ],
) -> dict[str, Any]:
    try:
        result = authentication_service.disable_account(
            actor_user_id=principal.owner_id,
            actor_roles=principal.roles,
            user_id=user_id,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    try:
        result["revoked_api_keys"] = (
            device_security_service.revoke_all_api_keys(
                user_id=user_id
            )
        )
    except Exception:
        result["revoked_api_keys"] = 0

    _record_administrative_action(
        principal=principal,
        action="account_disabled",
        target_user_id=user_id,
        metadata={
            "previous_status": result["previous_status"],
            "revoked_sessions": result[
                "revoked_sessions"
            ],
            "revoked_api_keys": result[
                "revoked_api_keys"
            ],
        },
    )
    return {"success": True, **result}


@router.post("/accounts/{user_id}/unlock")
def unlock_account(
    user_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_administrator),
    ],
) -> dict[str, Any]:
    try:
        result = authentication_service.unlock_account(
            actor_user_id=principal.owner_id,
            actor_roles=principal.roles,
            user_id=user_id,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    _record_administrative_action(
        principal=principal,
        action="account_unlocked",
        target_user_id=user_id,
        metadata={
            "previous_status": result["previous_status"],
        },
    )
    return {"success": True, **result}


@router.post("/accounts/{user_id}/roles/{role}")
def assign_account_role(
    user_id: str,
    role: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_administrator),
    ],
) -> dict[str, Any]:
    try:
        result = authentication_service.assign_account_role(
            actor_user_id=principal.owner_id,
            actor_roles=principal.roles,
            user_id=user_id,
            role=role,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    _record_administrative_action(
        principal=principal,
        action="role_assigned",
        target_user_id=user_id,
        changed=result["changed"],
        metadata={"role": result["role"]},
    )
    return {"success": True, **result}


@router.delete("/accounts/{user_id}/roles/{role}")
def remove_account_role(
    user_id: str,
    role: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_administrator),
    ],
) -> dict[str, Any]:
    try:
        result = authentication_service.remove_account_role(
            actor_user_id=principal.owner_id,
            actor_roles=principal.roles,
            user_id=user_id,
            role=role,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc

    _record_administrative_action(
        principal=principal,
        action="role_removed",
        target_user_id=user_id,
        changed=result["changed"],
        metadata={"role": result["role"]},
    )
    return {"success": True, **result}


__all__ = [
    "assign_account_role",
    "disable_account",
    "enable_account",
    "get_account",
    "list_accounts",
    "remove_account_role",
    "router",
    "unlock_account",
]
