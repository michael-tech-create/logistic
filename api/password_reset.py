"""Email-based password recovery for the desk's existing custom accounts."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import time
from urllib.parse import urlsplit, urlunsplit

from api import store

logger = logging.getLogger(__name__)
RESET_MESSAGE = "If an account exists for that email, a reset link will arrive shortly. Check your inbox and spam folder. You can request another link after one minute."
INVALID_LINK = "This reset link is invalid, expired, or already used. Request a new link."


def reset_page_url() -> str:
    configured = os.environ.get("PASSWORD_RESET_URL")
    if configured:
        parsed = urlsplit(configured)
    else:
        origin = os.environ.get("DASHBOARD_URL") or os.environ.get("PAYSTACK_CALLBACK_URL")
        if not origin and os.environ.get("RENDER") == "true":
            raise RuntimeError("Password recovery is not available yet. Please contact your workspace administrator.")
        parsed = urlsplit(origin or "http://localhost:3000")
        parsed = parsed._replace(path="/reset-password", query="", fragment="")
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme != "https" and not (local and parsed.scheme == "http")):
        raise RuntimeError("Password recovery is not available yet. Please contact your workspace administrator.")
    return urlunsplit(parsed)


def ensure_email_ready() -> str:
    if not os.environ.get("SMTP_HOST") or not (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")):
        raise RuntimeError("Password recovery email is not available yet. Please contact your workspace administrator.")
    page_url = reset_page_url()
    store.ensure_password_reset_ready()
    return page_url


def send_reset_link(email: str, page_url: str) -> None:
    """Run after returning the same response for every email address."""
    from automate import send_email

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    try:
        if not store.issue_password_reset(email, token_hash, now + 1800, now):
            return
        # Fragments stay out of HTTP access logs and are removed by the reset UI.
        link = f"{page_url}#token={token}"
        sent = send_email(email, "Reset your Clearing Desk password", f"A password reset was requested for your Clearing Desk account.\n\nOpen this link to choose a new password:\n{link}\n\nThis link expires in 30 minutes and can be used once. Requesting a newer link replaces the previous one.\n\nIf you did not request this, you can ignore this email. Your password has not changed.")
        if not sent:
            logger.warning("Password reset email could not be delivered.")
    except Exception:
        # Do not log tokens, addresses, or SMTP credentials through exceptions.
        logger.error("Password reset delivery failed. Check email and database configuration.")


def reset_password(token: str, password: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError(INVALID_LINK)
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not store.complete_password_reset(digest, store._hash_password(password), int(time.time())):
        raise ValueError(INVALID_LINK)
