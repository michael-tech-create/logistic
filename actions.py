"""Pay a party or file a cargo release only when a rail answers. Otherwise queue a person."""

from __future__ import annotations

import json
import os
import urllib.request

from api.store import queue_human_review


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "logistics-quote-api/1.0"},
        method="POST",
    )
    token = os.environ.get("ACTION_BEARER")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode()
    body = json.loads(raw) if raw else {}
    if response.status >= 300 or body.get("ok") is False:
        raise RuntimeError(body.get("detail") or f"Rail returned {response.status}")
    return body


def attempt(kind: str, record: dict, chat_id: str | None) -> dict:
    commercial = record.get("commercial") or {}
    summary = f"{kind} {commercial.get('quote_reference_id') or ''} {commercial.get('vendor_name') or ''}".strip()
    url = os.environ.get("PAYOUT_URL") if kind == "pay" else os.environ.get("CUSTOMS_CLEAR_URL")
    if not url:
        review = queue_human_review(kind, summary, chat_id, "The rail is not configured.")
        return {"done": False, "review_id": review["id"], "note": "No rail is configured, so this is waiting for a person."}
    try:
        result = _post(url, {"kind": kind, "chat_id": chat_id, "record": record})
    except Exception as exc:  # noqa: BLE001 — a down rail must become a review, not a fake payment
        review = queue_human_review(kind, summary, chat_id, str(exc)[:300])
        return {"done": False, "review_id": review["id"], "note": "The rail is down, so this is waiting for a person."}
    return {"done": True, "review_id": None, "note": result.get("note") or f"{kind} was accepted by the rail.", "rail": result}
