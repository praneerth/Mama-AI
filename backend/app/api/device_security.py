"""Trusted-device and account API-key endpoints for Mama AI."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.auth import (
    AuthenticatedPrincipal,
    require_account_session_principal,
    require_principal,
)
from app.core.device_security import API_KEY_SCOPES
from app.core.device_security_service import (
    APIKeyLimitError,
    APIKeyNotFoundError,
    DeviceNotFoundError,
    DeviceSecurityConfigurationError,
    InvalidDeviceSecurityPasswordError,
    device_security_service,
)
from app.database.security_event_db import record_security_event_safely


router = APIRouter(
    prefix="/auth/security",
    tags=["Account Security"],
)


class PasswordConfirmationRequest(BaseModel):
    current_password: str


class APIKeyCreateRequest(BaseModel):
    name: str
    scopes: list[str]
    current_password: str
    expires_in_days: int | None = None


class APIKeyRotateRequest(BaseModel):
    current_password: str
    expires_in_days: int | None = None


def require_account_security_principal(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> AuthenticatedPrincipal:
    return require_account_session_principal(principal)


def _security_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidDeviceSecurityPasswordError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is invalid.",
        )
    if isinstance(exc, (DeviceNotFoundError, APIKeyNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, APIKeyLimitError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, DeviceSecurityConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, (TypeError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Account security action failed.")


def _record_action(
    *,
    event_type: str,
    message: str,
    principal: AuthenticatedPrincipal,
    request: Request,
    metadata: dict[str, Any],
) -> None:
    record_security_event_safely(
        event_type="account_administration",
        severity="info",
        owner_id=principal.owner_id,
        request_method=request.method,
        request_path=request.url.path,
        status_code=200,
        message=message,
        metadata={
            "scope": "account_device_api_key_security",
            "action": event_type,
            **metadata,
        },
    )


@router.get("/devices")
def list_trusted_devices(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
    device_status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    try:
        devices = device_security_service.list_devices(
            user_id=principal.owner_id,
            status=device_status,
            limit=limit,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    return {
        "success": True,
        "current_session_id": principal.session_id,
        "devices": devices,
    }


@router.get("/devices/{device_id}/sessions")
def list_trusted_device_sessions(
    device_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
    limit: int = 100,
) -> dict[str, Any]:
    try:
        sessions = device_security_service.list_device_sessions(
            user_id=principal.owner_id,
            device_id=device_id,
            limit=limit,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    return {
        "success": True,
        "device_id": device_id,
        "sessions": sessions,
    }


@router.post("/devices/{device_id}/trust")
def trust_device(
    device_id: str,
    payload: PasswordConfirmationRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        device = device_security_service.set_device_trust(
            user_id=principal.owner_id,
            device_id=device_id,
            trusted=True,
            current_password=payload.current_password,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    _record_action(
        event_type="trusted_device_enabled",
        message="Account device was marked trusted.",
        principal=principal,
        request=request,
        metadata={"device_id": device_id},
    )
    return {"success": True, "device": device}


@router.post("/devices/{device_id}/untrust")
def untrust_device(
    device_id: str,
    payload: PasswordConfirmationRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        device = device_security_service.set_device_trust(
            user_id=principal.owner_id,
            device_id=device_id,
            trusted=False,
            current_password=payload.current_password,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    _record_action(
        event_type="trusted_device_disabled",
        message="Account device trust was removed.",
        principal=principal,
        request=request,
        metadata={"device_id": device_id},
    )
    return {"success": True, "device": device}


@router.post("/devices/{device_id}/revoke")
def revoke_device(
    device_id: str,
    payload: PasswordConfirmationRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        result = device_security_service.revoke_device(
            user_id=principal.owner_id,
            device_id=device_id,
            current_password=payload.current_password,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    _record_action(
        event_type="account_device_revoked",
        message="Account device and its active sessions were revoked.",
        principal=principal,
        request=request,
        metadata={
            "device_id": device_id,
            "revoked_sessions": result["revoked_sessions"],
        },
    )
    return {"success": True, **result}


@router.get("/api-keys")
def list_api_keys(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
    key_status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    try:
        keys = device_security_service.list_api_keys(
            user_id=principal.owner_id,
            status=key_status,
            limit=limit,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    return {
        "success": True,
        "available_scopes": sorted(API_KEY_SCOPES),
        "api_keys": keys,
    }


@router.post("/api-keys", status_code=201)
def create_api_key(
    payload: APIKeyCreateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        result = device_security_service.create_api_key(
            user_id=principal.owner_id,
            name=payload.name,
            scopes=payload.scopes,
            current_password=payload.current_password,
            expires_in_days=payload.expires_in_days,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    record = result["record"]
    _record_action(
        event_type="account_api_key_created",
        message="Account API key was created.",
        principal=principal,
        request=request,
        metadata={
            "key_id": record["key_id"],
            "scopes": record["scopes"],
            "expires_at": record["expires_at"],
        },
    )
    return {
        "success": True,
        "api_key": result["api_key"],
        "record": record,
        "notice": "Store this API key securely. It will not be shown again.",
    }


@router.post("/api-keys/{key_id}/rotate")
def rotate_api_key(
    key_id: str,
    payload: APIKeyRotateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        result = device_security_service.rotate_api_key(
            user_id=principal.owner_id,
            key_id=key_id,
            current_password=payload.current_password,
            expires_in_days=payload.expires_in_days,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    record = result["record"]
    _record_action(
        event_type="account_api_key_rotated",
        message="Account API key was rotated.",
        principal=principal,
        request=request,
        metadata={
            "old_key_id": key_id,
            "new_key_id": record["key_id"],
            "scopes": record["scopes"],
        },
    )
    return {
        "success": True,
        "api_key": result["api_key"],
        "record": record,
        "notice": "Store this API key securely. It will not be shown again.",
    }


@router.post("/api-keys/{key_id}/revoke")
def revoke_api_key(
    key_id: str,
    payload: PasswordConfirmationRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_account_security_principal),
    ],
) -> dict[str, Any]:
    try:
        record = device_security_service.revoke_api_key(
            user_id=principal.owner_id,
            key_id=key_id,
            current_password=payload.current_password,
        )
    except Exception as exc:
        raise _security_error(exc) from exc
    _record_action(
        event_type="account_api_key_revoked",
        message="Account API key was revoked.",
        principal=principal,
        request=request,
        metadata={"key_id": key_id},
    )
    return {"success": True, "record": record}


__all__ = [
    "APIKeyCreateRequest",
    "APIKeyRotateRequest",
    "PasswordConfirmationRequest",
    "create_api_key",
    "list_api_keys",
    "list_trusted_device_sessions",
    "list_trusted_devices",
    "require_account_security_principal",
    "revoke_api_key",
    "revoke_device",
    "rotate_api_key",
    "router",
    "trust_device",
    "untrust_device",
]
