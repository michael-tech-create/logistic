#!/usr/bin/env python3
"""Check Telegram setup without sending chat messages. Add --live for read-only API checks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Check getMe and getWebhookInfo; never send chat messages.")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent / ".env")
    mode = os.environ.get("TELEGRAM_DELIVERY_MODE", "polling").lower()
    token = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    secret = bool(os.environ.get("TELEGRAM_WEBHOOK_SECRET"))
    media = bool(os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY"))
    from automate import _dashboard_url
    print(f"Delivery mode: {mode}")
    for label, configured in (
        ("Telegram token", token), ("Webhook secret", secret),
        ("Photo / voice / scanned-PDF reader", media),
        ("Dashboard link buttons", bool(_dashboard_url())),
        ("Email copy", bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER")))),
        ("Payment execution provider", bool(os.environ.get("PAYOUT_URL"))),
        ("Customs execution provider", bool(os.environ.get("CUSTOMS_CLEAR_URL"))),
    ):
        print(f"{label}: {'configured' if configured else 'not configured'}")
    print("Text and readable PDF/TXT quotes use the local reader.")
    print("Payment and clearance requests wait for desk approval; missing providers cannot execute them.")
    valid = token and mode in {"polling", "webhook"} and (mode != "webhook" or secret)
    if args.live and token:
        from automate import telegram_api
        try:
            identity = telegram_api("getMe").get("result") or {}
            hook = telegram_api("getWebhookInfo").get("result") or {}
            print(f"Telegram credentials accepted for @{identity.get('username') or 'unknown'}.")
            print(f"Registered webhook: {'yes' if hook.get('url') else 'no'}")
            print(f"Pending Telegram updates: {hook.get('pending_update_count', 0)}")
            if mode == "polling" and hook.get("url"):
                print("Conflict: polling cannot run with a registered webhook. Choose one delivery mode.")
                valid = False
            if mode == "webhook" and not hook.get("url"):
                print("Webhook mode is selected, but no webhook is registered with Telegram.")
                valid = False
        except Exception as exc:
            print(f"Read-only Telegram check failed ({type(exc).__name__}). Check connectivity and token configuration.")
            valid = False
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
