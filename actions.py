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
    """Queue a person. Money and cargo release wait for that approval, then the rail."""
    commercial = record.get("commercial") or {}
    summary = f"{kind} {commercial.get('quote_reference_id') or ''} {commercial.get('vendor_name') or ''}".strip()
    review = queue_human_review(kind, summary, chat_id, "Waiting for a person to approve.", record)
    return {
        "done": False,
        "review_id": review["id"],
        "note": "A person has to approve this on the desk before any money is sent or cargo is cleared.",
    }


def execute_approved(row: dict) -> dict:
    """Call the payout or customs rail only after a person approved this review."""
    import json

    kind = row.get("kind")
    if kind not in {"pay", "clear"}:
        return {"done": True, "note": "Approved. This review does not send money or clear cargo."}
    url = os.environ.get("PAYOUT_URL") if kind == "pay" else os.environ.get("CUSTOMS_CLEAR_URL")
    if not url:
        return {"done": False, "note": "Approved by a person, but no rail is configured, so nothing was sent."}
    raw = row.get("payload")
    if not raw:
        return {"done": False, "note": "Approved by a person, but the quote was not stored, so nothing was sent."}
    record = json.loads(raw)
    try:
        result = _post(url, {"kind": kind, "chat_id": row.get("chat_id"), "record": record})
    except Exception as exc:  # noqa: BLE001 — approval must not become a fake payment
        return {"done": False, "note": f"The rail refused the request: {exc}"[:300]}
    return {"done": True, "note": result.get("note") or f"{kind} was accepted by the rail.", "rail": result}
