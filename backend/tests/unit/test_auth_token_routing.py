import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.auth import (
    authenticate_bearer_token,
)
from app.config import settings


class TestAuthenticationTokenRouting(
    unittest.TestCase
):

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ENABLED",
        True,
    )
    @patch.object(
        settings,
        "ACCOUNT_AUTH_ENABLED",
        True,
    )
    @patch.object(
        settings,
        "AUTH_SIGNING_SECRET",
        "",
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
    def test_opaque_invalid_token_returns_401_without_signing_secret(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            authenticate_bearer_token(
                "invalid-token-value"
            )

        self.assertEqual(
            context.exception.status_code,
            401,
        )
        self.assertEqual(
            context.exception.detail,
            "Bearer token is invalid.",
        )

    @patch.object(
        settings,
        "AUTH_STATIC_COMPATIBILITY_ENABLED",
        True,
    )
    @patch.object(
        settings,
        "ACCOUNT_AUTH_ENABLED",
        True,
    )
    @patch.object(
        settings,
        "AUTH_SIGNING_SECRET",
        "",
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
    def test_account_token_format_still_reports_configuration_error(
        self,
    ) -> None:
        with self.assertRaises(
            HTTPException
        ) as context:
            authenticate_bearer_token(
                "mama1.invalid.invalid"
            )

        self.assertEqual(
            context.exception.status_code,
            503,
        )


if __name__ == "__main__":
    unittest.main()
