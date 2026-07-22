import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import (
    HTTPAuthorizationCredentials,
)

from app.api.auth import (
    AuthenticatedPrincipal,
    authenticated_identity,
    require_principal,
)
from app.config import settings


class TestAuthenticationAPI(
    unittest.TestCase
):

    def credentials(
        self,
        token: str,
    ) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch.object(
        settings,
        "AUTH_TOKEN",
        "a" * 48,
    )
    @patch.object(
        settings,
        "AUTH_ENABLED",
        True,
    )
    def test_valid_bearer_token_returns_principal(
        self,
    ) -> None:
        principal = require_principal(
            self.credentials(
                "a" * 48
            )
        )

        self.assertEqual(
            principal.owner_id,
            "local-user",
        )

        self.assertEqual(
            principal.authentication_method,
            "bearer_token",
        )

        self.assertEqual(
            len(
                principal.token_fingerprint
            ),
            12,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch.object(
        settings,
        "AUTH_TOKEN",
        "a" * 48,
    )
    @patch.object(
        settings,
        "AUTH_ENABLED",
        True,
    )
    def test_missing_credentials_return_401(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            require_principal(None)

        self.assertEqual(
            context.exception.status_code,
            401,
        )

        self.assertEqual(
            context.exception.headers[
                "WWW-Authenticate"
            ],
            "Bearer",
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch.object(
        settings,
        "AUTH_TOKEN",
        "a" * 48,
    )
    @patch.object(
        settings,
        "AUTH_ENABLED",
        True,
    )
    def test_invalid_token_returns_401(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            require_principal(
                self.credentials(
                    "b" * 48
                )
            )

        self.assertEqual(
            context.exception.status_code,
            401,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch.object(
        settings,
        "AUTH_TOKEN",
        "short",
    )
    @patch.object(
        settings,
        "AUTH_ENABLED",
        True,
    )
    def test_short_server_token_returns_503(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            require_principal(
                self.credentials(
                    "short"
                )
            )

        self.assertEqual(
            context.exception.status_code,
            503,
        )

    @patch.object(
        settings,
        "AUTH_OWNER_ID",
        "local-user",
    )
    @patch.object(
        settings,
        "AUTH_TOKEN",
        "",
    )
    @patch.object(
        settings,
        "AUTH_ENABLED",
        False,
    )
    def test_deliberately_disabled_auth_is_visible(
        self,
    ) -> None:
        principal = require_principal(
            None
        )

        self.assertEqual(
            principal.owner_id,
            "local-user",
        )

        self.assertEqual(
            principal.authentication_method,
            "development_auth_disabled",
        )

        self.assertIsNone(
            principal.token_fingerprint
        )

    def test_auth_me_does_not_return_token(
        self,
    ) -> None:
        principal = AuthenticatedPrincipal(
            owner_id="local-user",
            authentication_method="bearer_token",
            token_fingerprint="abc123def456",
        )

        response = authenticated_identity(
            principal
        )

        self.assertTrue(
            response["success"]
        )

        self.assertNotIn(
            "token",
            response["principal"],
        )

        self.assertEqual(
            response["principal"][
                "owner_id"
            ],
            "local-user",
        )


if __name__ == "__main__":
    unittest.main()