"""Keep human authorization separate from submission to a configured provider."""

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
    company_id = record.get("company_id") or (record.get("business") or {}).get("id")
    review = queue_human_review(kind, summary, chat_id, "Waiting for a person to approve.", record, company_id=company_id)
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
        provider = "payment" if kind == "pay" else "customs"
        return {"done": False, "status": "approved", "note": f"Approval saved. No {provider} provider is connected, so nothing was sent. Ask your administrator to connect the provider, then use Send to provider."}
    raw = row.get("payload")
    if not raw:
        return {"done": False, "status": "approved", "note": "Approval saved, but the stored quote is missing. Nothing was sent. Ask your administrator to restore the quote before sending."}
    try:
        record = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(record, dict):
            raise ValueError("Expected a quote object")
    except (TypeError, ValueError):
        return {"done": False, "status": "approved", "note": "Approval saved, but the stored quote cannot be read. Nothing was sent. Ask your administrator to repair the quote before sending."}
    try:
        result = _post(url, {"kind": kind, "chat_id": row.get("chat_id"), "record": record})
    except Exception as exc:  # noqa: BLE001 — approval must not become a fake payment
        # A timeout can happen after a provider accepts a payment. Never retry it
        # automatically or put it back in the human approval queue.
        return {"done": False, "status": "execution_uncertain", "note": f"Approval saved. The provider did not confirm the result. Check with the provider before taking further action; do not submit this request again. Details: {exc}"[:500]}
    return {"done": True, "status": "executed", "note": result.get("note") or "Request accepted by the provider. Check the provider for its final outcome.", "rail": result}
