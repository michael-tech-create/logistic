"""Read each emailed document as a separate, deduplicated workspace quote."""
from __future__ import annotations

import hashlib
from email.utils import parseaddr
from api import store
import operations_store as state
from media_intake import email_sources


def ingest_email(message, raw: bytes):
    from customs import find_business, load_businesses
    from automate import ingest_text, send_email
    from desk_ops import save_record
    sender = parseaddr(message.get("From") or "")[1]
    business = find_business(load_businesses() + store.company_businesses(), email_from=sender)
    if not business: return {"ignored": True, "records": []}
    user = store.user_by_company(business["id"])
    if len(raw) > 30 * 1024 * 1024: raise ValueError("The email is too large. Send smaller attachments.")
    message_key = hashlib.sha256((business["id"] + ":").encode() + raw).hexdigest()
    complete = state.get("email_intake", message_key)
    if complete and complete["payload"].get("done"): return {"duplicate": True, "records": []}
    sources = email_sources(message)
    if user and len(sources) > user["quota_remaining"]:
        # Retry after a partial import can reuse the receipts already debited.
        remaining = sum(
            not state.get("email_parts", message_key + f":{index}")
            and not state.was_charged(user["id"], "mail-" + hashlib.sha256((message_key + f":{index}").encode()).hexdigest()[:32])
            for index in range(len(sources))
        )
        if remaining > user["quota_remaining"]: raise PermissionError("Not enough parses for all attachments. Add capacity in Settings.")
    records = []
    for index, source in enumerate(sources):
        receipt = message_key + f":{index}"
        if state.get("email_parts", receipt): continue
        outcome = ingest_text(source["text"], business=business)
        record = outcome["record"]
        if not record.get("line_items"): raise ValueError(f"No priced charges were found in {source['name']}.")
        record_id = "mail-" + hashlib.sha256(receipt.encode()).hexdigest()[:32]
        record.update(record_id=record_id, company_id=business["id"], source_channel="email", source_file=source["name"], source_text=source["text"])
        record["processing"]["milliseconds"] += source["reading_ms"]
        record["processing"]["scope"] = "attachment reading and quote preparation; excludes inbox polling, delivery, export, and human review"
        if user: state.charge_once(user["id"], record_id)
        save_record(record_id, record)
        if record.get("sync_error"): raise RuntimeError("Quote storage is temporarily unavailable.")
        state.put("email_parts", receipt, {"record_id": record_id}, business["id"])
        records.append(record)
    state.put("email_intake", message_key, {"done": True}, business["id"])
    if business.get("notify_email"):
        send_email(business["notify_email"], "Freight quotes ready to review", f"{len(records)} quote(s) were saved from your email. Open your Clearing Desk inbox to check routes, currencies, and charges, then export the client files. Customs and shipment charges can be calculated from sourced inputs inside each quote.")
    return {"records": records}
