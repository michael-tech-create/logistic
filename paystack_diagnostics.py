"""Check payment configuration without displaying credentials or creating payments."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Validate authentication with Paystack's read-only payment-session-timeout endpoint.")
    args = parser.parse_args()
    inherited = os.environ.get("PAYSTACK_SECRET_KEY")
    local = dotenv_values(ROOT / ".env").get("PAYSTACK_SECRET_KEY")
    load_dotenv(ROOT / ".env")
    from api.billing import PaystackConfigurationError, _request, _secret_key

    print("Configuration source:", "process environment" if inherited is not None else "project .env")
    if inherited is not None and local and inherited != local:
        print("The process key differs from .env; the process environment takes precedence.")
    try:
        secret = _secret_key()
    except PaystackConfigurationError as exc:
        print(str(exc))
        return 1
    print("Key format: secret key; mode:", "test" if secret.startswith("sk_test_") else "live")
    print("Callback URL configured:", bool(os.environ.get("PAYSTACK_CALLBACK_URL")))
    if not args.live:
        print("No network request made. Use --live to check authentication without creating a checkout or charging anyone.")
        return 0
    try:
        _request("/integration/payment_session_timeout")
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print("Paystack accepted the API key. No checkout was created and no money was charged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
