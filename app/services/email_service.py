"""Email service using Azure Communication Services (ACS).

Sends transactional emails for password resets and email verification.
Falls back to a no-op logger when ACS credentials are not configured (local dev).
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# Lazy import — azure-communication-email is only in requirements-prod.txt
try:
    from azure.communication.email import EmailClient
except ImportError:  # pragma: no cover
    EmailClient = None  # type: ignore[misc,assignment]

# ---------------------------------------------------------------------------
# Lazy singleton — initialised on first call
# ---------------------------------------------------------------------------
_client: EmailClient | None = None  # type: ignore[type-arg]


def _get_client():
    """Return a cached :class:`EmailClient`, or ``None`` when not configured."""
    global _client
    if _client is not None:
        return _client
    if EmailClient is None:
        logger.warning("acs_sdk_not_installed", hint="pip install azure-communication-email")
        return None
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


# ---------------------------------------------------------------------------
# Trial / engagement email sequence
# ---------------------------------------------------------------------------

def _email_wrapper(to_email: str, subject: str, html_body: str, email_type: str) -> bool:
    """Send an email using the ACS client. Returns True on success."""
    client = _get_client()
    if client is None:
        logger.info("email_skipped_no_client", type=email_type, to=to_email)
        return False
    try:
        message = {
            "senderAddress": settings.acs_sender_email,
            "recipients": {"to": [{"address": to_email}]},
            "content": {"subject": subject, "html": html_body},
        }
        poller = client.begin_send(message)
        result = poller.result()
        logger.info("email_sent", type=email_type, to=to_email, message_id=result.get("id"))
        return True
    except Exception as exc:
        logger.error("email_send_failed", type=email_type, to=to_email, error=str(exc))
        return False


def send_welcome_email(to_email: str, name: str) -> bool:
    """Day-0 welcome email after signup."""
    base = _base_url()
    html_body = f"""
    <html>
      <body style="font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
          <h2 style="color: #818cf8; margin-top: 0;">🎉 Welcome to PlagiarismGuard, {name}!</h2>
          <p>Your account is ready. Here's what you can do:</p>
          <ul style="padding-left: 20px; line-height: 1.8;">
            <li><strong>Plagiarism Detection</strong> — Check any text against 250M+ sources</li>
            <li><strong>AI Content Detector</strong> — Identify AI-generated passages</li>
            <li><strong>Smart Rewriter</strong> — Paraphrase with citations intact</li>
            <li><strong>Grammar &amp; Readability</strong> — Polish your writing</li>
          </ul>
          <div style="text-align: center; margin: 28px 0;">
            <a href="{base}/login"
               style="display: inline-block; padding: 14px 32px; background: #6366f1; color: #fff;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
              Start Your First Scan →
            </a>
          </div>
          <p style="font-size: 13px; color: #94a3b8;">
            You get <strong>3 free scans per day</strong>. Need more? Upgrade to Pro for unlimited scans.
          </p>
          <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
          <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">
            &copy; PlagiarismGuard &bull; <a href="{base}" style="color: #818cf8;">plagiarismguard.com</a>
          </p>
        </div>
      </body>
    </html>
    """
    return _email_wrapper(to_email, "Welcome to PlagiarismGuard! 🎉", html_body, "welcome")


def send_trial_usage_email(to_email: str, name: str, scans_used: int) -> bool:
    """Day-2 email showing usage summary and nudging toward upgrade."""
    base = _base_url()
    html_body = f"""
    <html>
      <body style="font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
          <h2 style="color: #818cf8; margin-top: 0;">📊 Your PlagiarismGuard Activity</h2>
          <p>Hi {name}, here's your usage so far:</p>
          <div style="background: #0f172a; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
            <div style="font-size: 48px; font-weight: 700; color: #818cf8;">{scans_used}</div>
            <div style="font-size: 14px; color: #94a3b8;">scans completed</div>
          </div>
          <p>With <strong>Pro</strong>, you get unlimited scans, priority processing, and detailed source reports.</p>
          <div style="text-align: center; margin: 28px 0;">
            <a href="{base}/login"
               style="display: inline-block; padding: 14px 32px; background: #6366f1; color: #fff;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
              Upgrade to Pro — ₹299/mo
            </a>
          </div>
          <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
          <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">
            &copy; PlagiarismGuard &bull; <a href="{base}" style="color: #818cf8;">plagiarismguard.com</a>
          </p>
        </div>
      </body>
    </html>
    """
    return _email_wrapper(to_email, f"You've run {scans_used} scans — unlock unlimited", html_body, "trial_usage")


def send_trial_ending_email(to_email: str, name: str) -> bool:
    """Day-5 email warning that free limits are restrictive. Offers discount."""
    base = _base_url()
    html_body = f"""
    <html>
      <body style="font-family: Inter, Arial, sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
          <h2 style="color: #818cf8; margin-top: 0;">⏰ Don't lose momentum, {name}</h2>
          <p>You've been using PlagiarismGuard on the free plan. Here's what you're missing on <strong>Pro</strong>:</p>
          <table style="width: 100%; margin: 20px 0; font-size: 14px;">
            <tr>
              <td style="padding: 8px 0; color: #94a3b8;">Daily scans</td>
              <td style="padding: 8px 0; color: #ef4444; text-align: center;">3</td>
              <td style="padding: 8px 0; color: #10b981; text-align: center; font-weight: 600;">Unlimited ✓</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; color: #94a3b8;">PDF export</td>
              <td style="padding: 8px 0; color: #ef4444; text-align: center;">Watermarked</td>
              <td style="padding: 8px 0; color: #10b981; text-align: center; font-weight: 600;">Clean + Certificate ✓</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; color: #94a3b8;">Source reports</td>
              <td style="padding: 8px 0; color: #ef4444; text-align: center;">Basic</td>
              <td style="padding: 8px 0; color: #10b981; text-align: center; font-weight: 600;">Detailed ✓</td>
            </tr>
          </table>
          <div style="background: #1a1a2e; border: 1px dashed #818cf8; border-radius: 8px; padding: 16px; text-align: center; margin: 20px 0;">
            <p style="margin: 0; font-size: 14px; color: #818cf8; font-weight: 600;">
              🎁 Save 16% with annual billing — just ₹250/mo
            </p>
          </div>
          <div style="text-align: center; margin: 28px 0;">
            <a href="{base}/login"
               style="display: inline-block; padding: 14px 32px; background: #6366f1; color: #fff;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">
              Upgrade Now →
            </a>
          </div>
          <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
          <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">
            &copy; PlagiarismGuard &bull; <a href="{base}" style="color: #818cf8;">plagiarismguard.com</a>
          </p>
        </div>
      </body>
    </html>
    """
    return _email_wrapper(to_email, "Your free scans are limited — upgrade for unlimited", html_body, "trial_ending")
