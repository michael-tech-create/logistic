"""Paystack subscription: ₦50,000 for 1,000 quote parses."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from api.store import PLANS, grant_plan

PAYSTACK_BASE = "https://api.paystack.co"
PAYSTACK_INIT = f"{PAYSTACK_BASE}/transaction/initialize"


class PaystackConfigurationError(RuntimeError):
    """The backend payment credential needs administrator attention."""


def _secret_key() -> str:
    secret = (os.environ.get("PAYSTACK_SECRET_KEY") or "").strip()
    # Hosting dashboards can preserve literal pasted quotes; dotenv normally
    # removes them. Normalize once for checkout, verification, and signatures.
    if len(secret) >= 2 and secret[0] == secret[-1] and secret[0] in "\"'":
        secret = secret[1:-1].strip()
    if not secret:
        raise PaystackConfigurationError("Payment checkout is not configured. Set PAYSTACK_SECRET_KEY on the Python API service and restart it.")
    if secret.startswith("pk_"):
        raise PaystackConfigurationError("The API has a Paystack public key. PAYSTACK_SECRET_KEY must contain the secret key from Paystack, beginning sk_test_ or sk_live_. Update the Python API service and restart it.")
    if not re.fullmatch(r"sk_(test|live)_[A-Za-z0-9]+", secret):
        raise PaystackConfigurationError("PAYSTACK_SECRET_KEY has an invalid format. Copy the complete secret key beginning sk_test_ or sk_live_ from Paystack into the Python API environment, then restart it.")
    return secret


def _message(payload: dict, secret: str) -> str:
    message = str(payload.get("message") or "Request rejected.")
    message = message.replace(secret, "[redacted]")
    message = re.sub(r"[sp]k_(?:live|test)_[A-Za-z0-9_-]+", "[redacted]", message)
    return " ".join(message.split())[:200]


def _request(path: str, body: dict | None = None) -> dict:
    secret = _secret_key()
    request = urllib.request.Request(
        f"{PAYSTACK_BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json", "User-Agent": "logistics-quote-api/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise PaystackConfigurationError("Paystack rejected the API secret key (401). Replace PAYSTACK_SECRET_KEY on the Python API service with a current secret key from your Paystack dashboard, then restart or redeploy the API.") from exc
        if exc.code == 403:
            raise PaystackConfigurationError("Paystack denied the API request (403). Check the secret key’s permissions and Paystack IP allowlist for your API server.") from exc
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except (ValueError, OSError):
            payload = {}
        detail = _message(payload if isinstance(payload, dict) else {}, secret)
        raise RuntimeError(f"Paystack could not complete the request ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Could not connect to Paystack. Please try again shortly.") from exc
    except ValueError as exc:
        raise RuntimeError("Paystack returned an unreadable response. Please try again shortly.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Paystack returned an unexpected response. Please try again shortly.")
    if payload.get("status") is not True:
        if str(payload.get("code") or "").lower() == "invalid_key" or str(payload.get("message") or "").lower() == "invalid key":
            raise PaystackConfigurationError("Paystack rejected the API secret key. Update PAYSTACK_SECRET_KEY on the Python API service and restart it.")
        raise RuntimeError(f"Paystack: {_message(payload, secret)}")
    return payload


def initialize_checkout(email: str, callback_url: str, plan_code: str = "quote-1000") -> dict:
    plan = PLANS.get(plan_code)
    if plan is None:
        raise RuntimeError("Choose quote-200 (₦15,000 / 200 parses) or quote-1000 (₦50,000 / 1,000 parses).")
    payload = _request("/transaction/initialize", {
        "email": email,
        "amount": plan["kobo"],
        "currency": "NGN",
        "callback_url": callback_url,
        "metadata": {"plan": plan_code, "parses": plan["parses"], "custom_fields": [
            {"display_name": "Plan", "variable_name": "plan", "value": f"{plan['parses']} quote parses"},
        ]},
    })
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("authorization_url") or not data.get("reference"):
        raise RuntimeError("Paystack did not return a checkout link. Please try again.")
    return data


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    try:
        secret = _secret_key()
    except PaystackConfigurationError:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(digest, signature)


def apply_event(event: dict) -> dict | None:
    if event.get("event") != "charge.success":
        return None
    data = event.get("data") or {}
    metadata = data.get("metadata") or {}
    plan_code = metadata.get("plan")
    plan = PLANS.get(plan_code or "")
    if plan is None:
        return None
    if data.get("currency") != "NGN" or int(data.get("amount") or 0) < plan["kobo"]:
        return None
    email = (data.get("customer") or {}).get("email")
    if not email:
        return None
    return grant_plan(email, data.get("reference"), plan_code)


def verify_transaction(reference: str) -> dict:
    payload = _request(f"/transaction/verify/{quote(reference, safe='')}")
    data = payload.get("data") or {}
    if data.get("status") != "success":
        raise RuntimeError(f"Payment {reference} is {data.get('status') or 'not successful'}.")
    metadata = data.get("metadata") or {}
    plan_code = metadata.get("plan")
    plan = PLANS.get(plan_code or "")
    if plan is None or int(data.get("amount") or 0) < plan["kobo"]:
        raise RuntimeError("This payment is not the 200-parse or 1,000-parse plan.")
    email = (data.get("customer") or {}).get("email")
    if not email:
        raise RuntimeError("Paystack did not return a customer email.")
    return {"email": email, "reference": data.get("reference") or reference, "amount": data.get("amount"), "plan": plan_code}
