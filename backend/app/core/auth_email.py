"""
Synchronous SMTP delivery for account verification and password recovery.

Raw verification and reset tokens exist only in memory long enough to build
and send the message. They are never logged or persisted by this module.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

from app.config import settings
from app.database.auth_db import normalize_email


class AuthenticationEmailError(RuntimeError):
    """Base authentication-email error."""


class AuthenticationEmailConfigurationError(
    AuthenticationEmailError
):
    """SMTP or public-link configuration is incomplete."""


class AuthenticationEmailDeliveryError(
    AuthenticationEmailError
):
    """SMTP delivery failed."""


class SMTPAuthenticationEmailSender:
    """Build and send account-security email through configured SMTP."""

    def send_email_verification(
        self,
        *,
        user: dict[str, Any],
        token: str,
    ) -> None:
        email = normalize_email(
            str(user["email"])
        )
        link = self._public_link(
            path="verify-email",
            token=token,
        )
        display_name = str(
            user.get("display_name")
            or "Mama AI user"
        )
        body = (
            f"Hello {display_name},\n\n"
            "Verify your Mama AI email address using this link:\n"
            f"{link}\n\n"
            "This link expires automatically and can be used only once.\n"
        )
        self._send(
            recipient=email,
            subject="Verify your Mama AI email",
            body=body,
        )

    def send_password_reset(
        self,
        *,
        user: dict[str, Any],
        token: str,
    ) -> None:
        email = normalize_email(
            str(user["email"])
        )
        link = self._public_link(
            path="reset-password",
            token=token,
        )
        display_name = str(
            user.get("display_name")
            or "Mama AI user"
        )
        body = (
            f"Hello {display_name},\n\n"
            "Reset your Mama AI password using this link:\n"
            f"{link}\n\n"
            "This link expires automatically and can be used only once. "
            "Ignore this message if you did not request a reset.\n"
        )
        self._send(
            recipient=email,
            subject="Reset your Mama AI password",
            body=body,
        )

    @staticmethod
    def development_token_exposure_enabled() -> bool:
        environment = str(
            settings.ENVIRONMENT
        ).strip().lower()
        return bool(
            settings.AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED
        ) and environment in {
            "development",
            "test",
        }

    def _public_link(
        self,
        *,
        path: str,
        token: str,
    ) -> str:
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationEmailConfigurationError(
                "Authentication email token is invalid."
            )

        base_url = str(
            settings.AUTH_PUBLIC_BASE_URL
        ).strip().rstrip("/")

        if not base_url:
            raise AuthenticationEmailConfigurationError(
                "Authentication public base URL is not configured."
            )

        return (
            base_url
            + "/"
            + path.strip("/")
            + "?token="
            + quote(token.strip(), safe="")
        )

    def _send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        host = str(
            settings.AUTH_SMTP_HOST
        ).strip()
        from_email = str(
            settings.AUTH_SMTP_FROM_EMAIL
        ).strip()
        username = str(
            settings.AUTH_SMTP_USERNAME
        ).strip()
        password = str(
            settings.AUTH_SMTP_PASSWORD
        )

        if not host or not from_email:
            raise AuthenticationEmailConfigurationError(
                "Authentication SMTP delivery is not configured."
            )

        if bool(username) != bool(password):
            raise AuthenticationEmailConfigurationError(
                "Authentication SMTP username and password must be "
                "configured together."
            )

        message = EmailMessage()
        message["From"] = from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(
                host=host,
                port=int(
                    settings.AUTH_SMTP_PORT
                ),
                timeout=float(
                    settings.AUTH_SMTP_TIMEOUT_SECONDS
                ),
            ) as smtp:
                smtp.ehlo()

                if bool(
                    settings.AUTH_SMTP_USE_TLS
                ):
                    smtp.starttls(
                        context=ssl.create_default_context()
                    )
                    smtp.ehlo()

                if username:
                    smtp.login(
                        username,
                        password,
                    )

                smtp.send_message(
                    message
                )

        except AuthenticationEmailConfigurationError:
            raise

        except (
            OSError,
            smtplib.SMTPException,
            ValueError,
        ) as exc:
            raise AuthenticationEmailDeliveryError(
                "Authentication email could not be delivered."
            ) from exc


authentication_email_sender = SMTPAuthenticationEmailSender()


__all__ = [
    "AuthenticationEmailConfigurationError",
    "AuthenticationEmailDeliveryError",
    "AuthenticationEmailError",
    "SMTPAuthenticationEmailSender",
    "authentication_email_sender",
]
