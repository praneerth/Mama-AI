import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.auth import (
    AuthenticatedPrincipal,
    require_runtime_reader,
    require_security_event_reader,
)
from app.core.rbac import (
    PERMISSION_RUNTIME_READ,
    PERMISSION_SECURITY_EVENTS_READ,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_USER,
    permissions_for_roles,
)


def request_for(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
            "root_path": "",
        }
    )


class TestAPIPermissionDependencies(unittest.TestCase):

    def principal(self, *roles: str) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            owner_id="user-1",
            authentication_method="unit_test",
            roles=tuple(roles),
        )

    def test_auditor_and_admin_receive_operational_permissions(self) -> None:
        for role in (ROLE_AUDITOR, ROLE_ADMIN):
            permissions = permissions_for_roles((ROLE_USER, role))
            self.assertIn(PERMISSION_RUNTIME_READ, permissions)
            self.assertIn(PERMISSION_SECURITY_EVENTS_READ, permissions)

    def test_user_role_has_no_operational_permissions(self) -> None:
        permissions = permissions_for_roles((ROLE_USER,))
        self.assertNotIn(PERMISSION_RUNTIME_READ, permissions)
        self.assertNotIn(PERMISSION_SECURITY_EVENTS_READ, permissions)

    def test_auditor_can_read_runtime_and_security_events(self) -> None:
        principal = self.principal(ROLE_USER, ROLE_AUDITOR)
        self.assertIs(
            require_runtime_reader(
                request_for("/health/runtime"),
                principal,
            ),
            principal,
        )
        self.assertIs(
            require_security_event_reader(
                request_for("/security/events"),
                principal,
            ),
            principal,
        )

    def test_user_denial_is_audited_without_secret_data(self) -> None:
        principal = self.principal(ROLE_USER)
        with patch("app.api.auth.record_security_event_safely") as recorder:
            with self.assertRaises(HTTPException) as context:
                require_security_event_reader(
                    request_for("/security/events"),
                    principal,
                )
        self.assertEqual(context.exception.status_code, 403)
        kwargs = recorder.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "authorization_denied")
        self.assertEqual(
            kwargs["metadata"]["required_permission"],
            PERMISSION_SECURITY_EVENTS_READ,
        )
        self.assertNotIn("token", repr(kwargs).lower())


if __name__ == "__main__":
    unittest.main()
