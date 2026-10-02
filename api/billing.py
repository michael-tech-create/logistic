"""Paystack subscription: ₦50,000 for 1,000 quote parses."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

from api.store import PLANS, grant_plan

PAYSTACK_INIT = "https://api.paystack.co/transaction/initialize"


def initialize_checkout(email: str, callback_url: str, plan_code: str = "quote-1000") -> dict:
    plan = PLANS.get(plan_code)
    if plan is None:
        raise RuntimeError("Choose quote-200 (₦15,000 / 200 parses) or quote-1000 (₦50,000 / 1,000 parses).")
    secret = os.environ.get("PAYSTACK_SECRET_KEY")
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set.")
    body = json.dumps({
        "email": email,
        "amount": plan["kobo"],
        "currency": "NGN",
        "callback_url": callback_url,
        "metadata": {"plan": plan_code, "parses": plan["parses"], "custom_fields": [
            {"display_name": "Plan", "variable_name": "plan", "value": f"{plan['parses']} quote parses"},
        ]},
    }).encode()
    request = urllib.request.Request(
        PAYSTACK_INIT,
        data=body,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "User-Agent": "logistics-quote-api/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Paystack rejected checkout ({exc.code}): {detail}") from exc
    if not payload.get("status"):
        raise RuntimeError(payload.get("message") or "Paystack initialize failed")
    return payload["data"]


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not secret or not signature:
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
    secret = os.environ.get("PAYSTACK_SECRET_KEY")
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set.")
    request = urllib.request.Request(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={
            "Authorization": f"Bearer {secret}",
            "User-Agent": "logistics-quote-api/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Paystack could not verify {reference} ({exc.code}): {detail}") from exc
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
