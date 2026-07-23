import unittest
from unittest.mock import MagicMock, patch

from app.config import settings
from app.core.auth_email import (
    AuthenticationEmailConfigurationError,
    SMTPAuthenticationEmailSender,
)


class TestAuthenticationEmailSender(unittest.TestCase):
    TOKEN = "email-delivery-token-" + ("t" * 48)
    USER = {
        "email": "praneeth@example.com",
        "display_name": "Praneeth",
    }

    def setUp(self) -> None:
        self.sender = SMTPAuthenticationEmailSender()

    @patch.object(settings, "AUTH_SMTP_FROM_EMAIL", "")
    @patch.object(settings, "AUTH_SMTP_HOST", "")
    def test_missing_smtp_configuration(self) -> None:
        with self.assertRaises(AuthenticationEmailConfigurationError):
            self.sender.send_email_verification(
                user=self.USER,
                token=self.TOKEN,
            )

    @patch.object(settings, "AUTH_PUBLIC_BASE_URL", "https://mama.example")
    @patch.object(settings, "AUTH_SMTP_TIMEOUT_SECONDS", 10)
    @patch.object(settings, "AUTH_SMTP_USE_TLS", True)
    @patch.object(settings, "AUTH_SMTP_FROM_EMAIL", "security@mama.example")
    @patch.object(settings, "AUTH_SMTP_PASSWORD", "smtp-password")
    @patch.object(settings, "AUTH_SMTP_USERNAME", "smtp-user")
    @patch.object(settings, "AUTH_SMTP_PORT", 587)
    @patch.object(settings, "AUTH_SMTP_HOST", "smtp.example")
    @patch("app.core.auth_email.smtplib.SMTP")
    def test_verification_email_uses_tls_and_login(self, smtp_class) -> None:
        smtp = MagicMock()
        smtp_class.return_value.__enter__.return_value = smtp
        self.sender.send_email_verification(
            user=self.USER,
            token=self.TOKEN,
        )
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("smtp-user", "smtp-password")
        message = smtp.send_message.call_args.args[0]
        self.assertIn("verify-email", message.get_content())
        self.assertIn(self.TOKEN, message.get_content())

    @patch.object(settings, "ENVIRONMENT", "production")
    @patch.object(settings, "AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED", True)
    def test_production_never_exposes_development_token(self) -> None:
        self.assertFalse(
            self.sender.development_token_exposure_enabled()
        )


if __name__ == "__main__":
    unittest.main()
