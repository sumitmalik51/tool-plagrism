"""Email service using Azure Communication Services (ACS).

Sends transactional emails for password resets and email verification.
Falls back to a no-op logger when ACS credentials are not configured (local dev).
"""

from __future__ import annotations

import structlog
from azure.communication.email import EmailClient

from app.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton — initialised on first call
# ---------------------------------------------------------------------------
_client: EmailClient | None = None


def _get_client() -> EmailClient | None:
    """Return a cached :class:`EmailClient`, or ``None`` when not configured."""
    global _client
    if _client is not None:
        return _client
    conn = settings.acs_connection_string
    if not conn:
        logger.warning("acs_not_configured", hint="Set PG_ACS_CONNECTION_STRING to enable email")
        return None
    _client = EmailClient.from_connection_string(conn)
    return _client


def _base_url() -> str:
    """Return the public base URL of the app."""
    return settings.app_base_url.rstrip("/")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def send_password_reset_email(to_email: str, token: str) -> bool:
    """Send a password-reset link to the user.

    Returns ``True`` on success, ``False`` if email could not be sent.
    """
    client = _get_client()
    reset_url = f"{_base_url()}/forgot-password?token={token}"

    html_body = f"""
    <html>
      <body style="font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
          <h2 style="color: #818cf8; margin-top: 0;">🔒 Password Reset</h2>
          <p>We received a request to reset your password for your <strong>PlagiarismGuard</strong> account.</p>
          <p>Click the button below to set a new password. This link expires in <strong>1 hour</strong>.</p>
          <div style="text-align: center; margin: 28px 0;">
            <a href="{reset_url}"
               style="display: inline-block; padding: 14px 32px; background: #6366f1; color: #fff;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
              Reset Password
            </a>
          </div>
          <p style="font-size: 13px; color: #94a3b8;">
            If you didn't request this, you can safely ignore this email. Your password won't change.
          </p>
          <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
          <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">
            &copy; PlagiarismGuard &bull; <a href="{_base_url()}" style="color: #818cf8;">plagiarismguard.com</a>
          </p>
        </div>
      </body>
    </html>
    """

    if client is None:
        logger.info("email_skipped_no_client", type="password_reset", to=to_email, reset_url=reset_url)
        return False

    try:
        message = {
            "senderAddress": settings.acs_sender_email,
            "recipients": {"to": [{"address": to_email}]},
            "content": {
                "subject": "Reset your PlagiarismGuard password",
                "html": html_body,
            },
        }
        poller = client.begin_send(message)
        result = poller.result()
        logger.info("email_sent", type="password_reset", to=to_email, message_id=result.get("id"))
        return True
    except Exception as exc:
        logger.error("email_send_failed", type="password_reset", to=to_email, error=str(exc))
        return False


def send_verification_email(to_email: str, token: str) -> bool:
    """Send an email-verification link to the user.

    Returns ``True`` on success, ``False`` if email could not be sent.
    """
    client = _get_client()
    verify_url = f"{_base_url()}/verify-email?token={token}"

    html_body = f"""
    <html>
      <body style="font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
          <h2 style="color: #818cf8; margin-top: 0;">✉️ Verify Your Email</h2>
          <p>Welcome to <strong>PlagiarismGuard</strong>! Please verify your email address to unlock all features.</p>
          <div style="text-align: center; margin: 28px 0;">
            <a href="{verify_url}"
               style="display: inline-block; padding: 14px 32px; background: #6366f1; color: #fff;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
              Verify Email
            </a>
          </div>
          <p style="font-size: 13px; color: #94a3b8;">
            If you didn't create a PlagiarismGuard account, you can ignore this email.
          </p>
          <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
          <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">
            &copy; PlagiarismGuard &bull; <a href="{_base_url()}" style="color: #818cf8;">plagiarismguard.com</a>
          </p>
        </div>
      </body>
    </html>
    """

    if client is None:
        logger.info("email_skipped_no_client", type="verification", to=to_email, verify_url=verify_url)
        return False

    try:
        message = {
            "senderAddress": settings.acs_sender_email,
            "recipients": {"to": [{"address": to_email}]},
            "content": {
                "subject": "Verify your PlagiarismGuard email",
                "html": html_body,
            },
        }
        poller = client.begin_send(message)
        result = poller.result()
        logger.info("email_sent", type="verification", to=to_email, message_id=result.get("id"))
        return True
    except Exception as exc:
        logger.error("email_send_failed", type="verification", to=to_email, error=str(exc))
        return False
