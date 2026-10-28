"""HTTPS transactional email for hosts that block outbound SMTP."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def delivery_method() -> str:
    """A partly configured HTTPS provider must not silently fall back to SMTP."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("RESEND_FROM", "").strip()
    if key or sender:
        if not key or not sender:
            raise RuntimeError("Configure both RESEND_API_KEY and RESEND_FROM on the backend.")
        return "resend"
    if not os.environ.get("SMTP_HOST") or not (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")):
        raise RuntimeError("Configure HTTPS email delivery or SMTP on the backend.")
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise RuntimeError("SMTP_PORT must be a valid port number.") from None
    return "smtp"


def send_via_resend(to_address: str, subject: str, body: str) -> bool:
    """Return provider acceptance, not a claim that mail reached the inbox."""
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": os.environ["RESEND_FROM"].strip(), "to": [to_address], "subject": subject, "text": body}).encode(),
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}", "Content-Type": "application/json", "User-Agent": "clearing-desk/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read(65536))
        if isinstance(result, dict) and isinstance(result.get("id"), str) and result["id"]:
            return True
        logger.warning("HTTPS email response did not confirm acceptance.")
    except urllib.error.HTTPError as exc:
        # Provider responses can echo recipients or message content. Keep reset
        # links, addresses, credentials, and response bodies out of application logs.
        hints = {401: "check RESEND_API_KEY", 403: "check the verified sender and test-recipient restrictions", 422: "check sender and email configuration", 429: "check the provider sending quota"}
        logger.warning("HTTPS email rejected (HTTP %s); %s.", exc.code, hints.get(exc.code, "check the provider dashboard"))
        exc.close()
    except (OSError, ValueError):
        logger.warning("HTTPS email failed; check provider connectivity and configuration.")
    return False
