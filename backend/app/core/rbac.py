"""Role and permission definitions for Mama AI account authorization."""

from __future__ import annotations

from collections.abc import Iterable


ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_AUDITOR = "auditor"

ACCOUNT_ROLES = frozenset({
    ROLE_USER,
    ROLE_ADMIN,
    ROLE_AUDITOR,
})

PERMISSION_ACCOUNTS_READ = "accounts.read"
PERMISSION_ACCOUNTS_MANAGE = "accounts.manage"
PERMISSION_ROLES_MANAGE = "roles.manage"

ROLE_PERMISSIONS = {
    ROLE_USER: frozenset(),
    ROLE_AUDITOR: frozenset({
        PERMISSION_ACCOUNTS_READ,
    }),
    ROLE_ADMIN: frozenset({
        PERMISSION_ACCOUNTS_READ,
        PERMISSION_ACCOUNTS_MANAGE,
        PERMISSION_ROLES_MANAGE,
    }),
}


def validate_role(role: str) -> str:
    if not isinstance(role, str):
        raise TypeError("Account role must be text.")

    normalized = role.strip().lower()

    if normalized not in ACCOUNT_ROLES:
        raise ValueError(
            "Account role must be one of: "
            + ", ".join(sorted(ACCOUNT_ROLES))
            + "."
        )

    return normalized


def normalize_roles(
    roles: Iterable[str] | str,
    *,
    ensure_user: bool = False,
) -> tuple[str, ...]:
    if isinstance(roles, str):
        values = roles.split(",")
    else:
        values = list(roles)

    normalized = {
        validate_role(value)
        for value in values
        if isinstance(value, str) and value.strip()
    }

    if ensure_user:
        normalized.add(ROLE_USER)

    return tuple(sorted(normalized))


def permissions_for_roles(
    roles: Iterable[str] | str,
) -> tuple[str, ...]:
    permissions: set[str] = set()

    for role in normalize_roles(roles):
        permissions.update(
            ROLE_PERMISSIONS[role]
        )

    return tuple(sorted(permissions))


def has_permission(
    roles: Iterable[str] | str,
    permission: str,
) -> bool:
    if not isinstance(permission, str):
        return False

    normalized = permission.strip().lower()

    if not normalized:
        return False

    return normalized in permissions_for_roles(
        roles
    )


__all__ = [
    "ACCOUNT_ROLES",
    "PERMISSION_ACCOUNTS_MANAGE",
    "PERMISSION_ACCOUNTS_READ",
    "PERMISSION_ROLES_MANAGE",
    "ROLE_ADMIN",
    "ROLE_AUDITOR",
    "ROLE_PERMISSIONS",
    "ROLE_USER",
    "has_permission",
    "normalize_roles",
    "permissions_for_roles",
    "validate_role",
]
