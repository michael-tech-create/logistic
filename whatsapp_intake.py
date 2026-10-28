"""WaAPI inbound quotes, with durable jobs and workspace-scoped linking."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from api import store
import operations_store as state
from media_intake import MAX_BYTES, read_document

logger = logging.getLogger(__name__)
_running = set()
_lock = threading.Lock()


def configured():
    return bool(os.environ.get("WAAPI_TOKEN") and os.environ.get("WAAPI_INSTANCE_ID") and len(os.environ.get("WAAPI_WEBHOOK_SECRET", "")) >= 32)


def action(name, payload):
    instance = os.environ.get("WAAPI_INSTANCE_ID", "")
    if not instance.isdigit() or not os.environ.get("WAAPI_TOKEN"):
        raise RuntimeError("WhatsApp is not configured.")
    request = urllib.request.Request(f"https://waapi.app/api/v1/instances/{instance}/client/action/{name}", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {os.environ['WAAPI_TOKEN']}", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = json.loads(response.read(1024 * 1024))
    inner = raw.get("data") or {}
    if raw.get("status") != "success" or inner.get("status") != "success":
        raise RuntimeError("WhatsApp provider did not confirm the action.")
    return inner.get("data") or {}


def link_code(company_id):
    token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(token.encode()).hexdigest()
    state.put("wa_link_tokens", digest, {"expires_at": time.time() + 600, "used": False}, company_id, expected=0)
    return {"command": f"/link {token}", "expires_in": 600}


def link_chat(chat, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = state.get("wa_link_tokens", digest)
    if not row or row["payload"].get("used") or row["payload"].get("expires_at", 0) < time.time():
        return "This connection code is invalid or expired. Create a new code in Connections on your desk."
    old = state.get("wa_links", chat)
    if old and old["payload"].get("active") and old["company_id"] != row["company_id"]:
        return "This number already belongs to another workspace. Disconnect it from that workspace's Connections page first."
    if not state.put("wa_link_tokens", digest, {"used": True}, row["company_id"], expected=row["revision"]):
        return "This connection code has already been used. Create a new one on the desk."
    if not state.put("wa_links", chat, {"active": True}, row["company_id"], expected=old["revision"] if old else 0):
        return "The connection changed while linking. Create a fresh code and try again."
    return "Connected to your clearing desk. Send a quote as text, PDF, photo, or voice note. I will prepare the details for your review."


def enqueue(payload):
    if str(payload.get("instanceId")) != os.environ.get("WAAPI_INSTANCE_ID"):
        raise ValueError("Wrong WhatsApp instance.")
    if payload.get("event") != "message": return None
    message = (payload.get("data") or {}).get("message") or {}
    metadata = message.get("_data") or {}
    identifier = message.get("id") or metadata.get("id") or {}
    identifier = identifier.get("_serialized") if isinstance(identifier, dict) else identifier
    chat = message.get("from") or metadata.get("from") or ""
    if message.get("fromMe") or (metadata.get("id") or {}).get("fromMe"): return None
    if not re.fullmatch(r"\d{8,16}@c\.us", chat): return None  # Private phone chats only.
    if not isinstance(identifier, str) or not identifier.startswith(f"false_{chat}_") or len(identifier) > 300:
        raise ValueError("Invalid inbound message identifier.")
    # Never persist user-provided media URLs; downloads come from WaAPI by message ID.
    key = "wa-" + hashlib.sha256(identifier.encode()).hexdigest()[:32]
    state.put("wa_jobs", key, {"status": "pending", "message_id": identifier, "chat": chat, "attempts": 0, "available_at": 0, "received_at": time.time()}, expected=0)
    return key


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def media_text(identifier):
    result = action("download-media", {"messageId": identifier})
    media = result.get("media") or {}
    target = urlsplit(media.get("url") or "")
    if target.scheme != "https" or target.hostname != "media.waapi.app" or target.username or target.password or target.port not in {None, 443}:
        raise ValueError("The provider returned an unsupported media location.")
    if int(media.get("filesize") or 0) > MAX_BYTES: raise ValueError("Send a file up to 20 MB.")
    # No authentication headers follow the download URL, and redirects are refused.
    with urllib.request.build_opener(_NoRedirect).open(target.geturl(), timeout=30) as response:
        raw = response.read(MAX_BYTES + 1)
    return read_document(raw, media.get("filename") or "", media.get("mimetype") or "")


def _record(record_id, company_id):
    from desk_ops import load_record
    from supabase_sync import get_quote
    record = get_quote(record_id, company_id) if store.using_cloud() else load_record(record_id)
    if not record or record.get("company_id") != company_id: raise ValueError("The quote could not be found in this workspace.")
    return record


def _save(record):
    from desk_ops import save_record
    save_record(record["record_id"], record)
    if record.get("sync_error"): raise RuntimeError("Quote storage is temporarily unavailable.")


def process_message(job):
    from automate import _dashboard_url, _missing_details, _looks_like_new_quote, _merge_follow_up, ingest_text
    chat = job["chat"]
    fetched = action("get-message-by-id", {"messageId": job["message_id"], "includeMedia": False})
    message = fetched.get("message") or fetched
    raw = message.get("_data") or {}
    if (message.get("from") or raw.get("from")) != chat or message.get("fromMe") or (raw.get("id") or {}).get("fromMe"):
        raise ValueError("The provider could not verify this incoming sender.")
    text = (message.get("body") or raw.get("body") or "").strip()
    command, _, argument = text.partition(" ")
    command = command.lower().lstrip("/") if text.startswith("/") or text.lower() in {"start", "help", "hi", "hello"} else ""
    if command == "link": return {"text": link_chat(chat, argument.strip())}
    link = state.get("wa_links", chat)
    if not link or not link["payload"].get("active"):
        return {"text": "Welcome to Clearing Desk. Open Connections on your desk, create a WhatsApp connection code, and send the /link command here. " + (_dashboard_url() or "")}
    company_id = link["company_id"]
    user = store.user_by_company(company_id)
    if not user: raise ValueError("Your workspace is unavailable. Sign in on the desk.")
    from api.main import _business
    business = _business(user)
    session = state.get("wa_sessions", chat)
    context = session["payload"] if session and session["company_id"] == company_id else {}
    if command in {"start", "help", "hi", "hello"}:
        return {"text": "Send quote text, PDF, image, or audio. Reply with missing details when asked.\n/new — start a quote\n/check — confirm the displayed quote\n/pdf or /excel — download a checked quote\n/status — workspace and latest quote\n/cancel — discard a draft\nPayments and customs submissions require approval on your desk."}
    if command in {"new", "cancel"}:
        state.put("wa_sessions", chat, {}, company_id)
        return {"text": "Ready for a new quote. Saved quotes remain in your desk."}
    if command == "status":
        return {"text": f"Workspace: {business['legal_name']}\n{user['quota_remaining']} parses left.\nLatest quote: {context.get('record_id') or 'none'}\n" + (_dashboard_url() or "")}
    if command in {"check", "pdf", "excel", "xlsx", "pay", "clear"}:
        if not context.get("record_id"): return {"text": "Send a quote first, or open a saved quote on your desk."}
        record = _record(context["record_id"], company_id)
        missing = _missing_details(record)
        if command == "check":
            if missing: return {"text": "Please provide " + ", ".join(missing) + " before checking this quote."}
            record["desk_review"] = {"status": "reviewed", "reviewed_at": datetime.now(timezone.utc).isoformat(), "reviewed_by": "Linked WhatsApp user"}
            _save(record)
            return {"text": "Quote checked. Send /pdf or /excel for your client file. Payment and clearance approvals are separate."}
        if command in {"pay", "clear"}: return {"text": "Open your desk to review and approve this request: " + (_dashboard_url() or "Sign in to your workspace.")}
        if not record.get("desk_review"): return {"text": "Review the displayed charges first, then send /check before downloading."}
        from api.exports import build_pdf, build_xlsx
        kind = "pdf" if command == "pdf" else "xlsx"
        data = build_pdf([record], business["legal_name"]) if kind == "pdf" else build_xlsx([record], business["legal_name"])
        return {"text": "Your checked client quote.", "mediaBase64": base64.b64encode(data).decode(), "mediaName": f"{record['record_id']}.{kind}"}
    if text.startswith("/"):
        return {"text": "Use /help for available commands, /new to start another quote, or /cancel to discard the current draft."}
    if int(user.get("quota_remaining") or 0) <= 0 and not context.get("draft") and not state.was_charged(user["id"], job["key"]):
        return {"text": "Your parse allowance is used up. Open Settings on your desk to add capacity."}
    started = time.perf_counter()
    if message.get("hasMedia") or raw.get("type") in {"ptt", "audio", "image", "document"} or message.get("type") in {"ptt", "audio", "image", "document"}:
        text = (text + "\n" + media_text(job["message_id"])).strip()
    if not text or len(text) > 200_000: raise ValueError("Send quote text or a supported attachment.")
    continuing = bool(context.get("draft")) and not _looks_like_new_quote(text)
    if continuing:
        missing = _missing_details(_record(context["record_id"], company_id))
        if missing and missing[0] in {"origin", "destination"} and len(text.splitlines()) == 1 and not re.search(r"origin|destination|charges|freight|NGN|USD|\$|₦", text, re.I):
            text = f"{missing[0].title()}: {text}"
        text = _merge_follow_up(context["draft"], text)
    outcome = ingest_text(text, business=business)
    record = outcome["record"]
    if not record.get("line_items"): return {"text": "I could not find priced charges. Send the carrier quote with amounts and currencies."}
    record_id = context["record_id"] if continuing else job["key"]
    record.update(record_id=record_id, company_id=company_id, source_text=text, source_channel="whatsapp")
    record["processing"] = {"milliseconds": round((time.perf_counter() - started) * 1000), "scope": "attachment reading and quote preparation; excludes queue, delivery, and human review"}
    state.charge_once(user["id"], record_id)
    _save(record)
    missing = _missing_details(record)
    state.put("wa_sessions", chat, {"record_id": record_id, "draft": text if missing else ""}, company_id)
    reply = outcome["notice"] + ("\n\nPlease provide: " + ", ".join(missing) if missing else "\n\nReview these details against the source, then send /check. Use /new to start a different quote.")
    return {"text": reply}


def run_job(key):
    row = state.get("wa_jobs", key)
    if not row: return
    job = row["payload"]
    now = time.time()
    if job.get("status") != "pending" or job.get("available_at", 0) > now: return
    chat = job["chat"]
    lock = state.get("wa_locks", chat)
    if lock and lock["payload"].get("until", 0) > now: return
    claimed_lock = state.put("wa_locks", chat, {"until": now + 900, "job": key}, expected=lock["revision"] if lock else 0)
    if not claimed_lock: return
    try:
        first = state.first_chat_job(chat)
        if first and first["key"] != key: return
        job = {**job, "status": "processing", "attempts": job.get("attempts", 0) + 1, "claimed_at": now, "key": key}
        claimed = state.put("wa_jobs", key, job, expected=row["revision"])
        if not claimed: return
        try:
            reply = job.get("reply") or process_message(job)
        except (ValueError, PermissionError) as exc:
            reply = {"text": str(exc)[:1000]}
        except Exception:
            state.put("wa_jobs", key, {**job, "status": "failed" if job["attempts"] >= 3 else "pending", "available_at": time.time() + 30})
            logger.warning("WhatsApp intake deferred; check provider and storage configuration.")
            return
        # Record the prepared reply before sending. A timeout cannot safely prove
        # whether a provider accepted it, so delivery is not retried automatically.
        sending = state.put("wa_jobs", key, {**job, "status": "sending", "reply": reply})
        try:
            pinned = os.environ.get("WAAPI_CHAT_ID", "").strip()
            if pinned and (pinned if "@" in pinned else pinned + "@c.us") != chat:
                raise RuntimeError("Trial recipient restriction: refusing to redirect a private quote.")
            if reply.get("mediaBase64"):
                action("send-media", {"chatId": chat, "mediaBase64": reply["mediaBase64"], "mediaName": reply["mediaName"], "asDocument": True, "mediaCaption": reply["text"]})
            else:
                text = reply["text"]
                for offset in range(0, len(text), 3500): action("send-message", {"chatId": chat, "message": text[offset:offset + 3500]})
            state.put("wa_jobs", key, {"status": "done", "record_id": key}, expected=sending["revision"])
        except Exception:
            state.put("wa_jobs", key, {"status": "delivery_uncertain", "record_id": key}, expected=sending["revision"])
            logger.warning("WhatsApp reply was not confirmed; inspect provider delivery logs before retrying.")
    finally:
        state.put("wa_locks", chat, {"until": 0}, expected=claimed_lock["revision"])


def schedule_pending():
    if not configured(): return
    from workers import submit
    for row in state.listing("wa_jobs", status="sending"):
        if row["updated_at"] < time.time() - 900:
            state.put("wa_jobs", row["key"], {"status": "delivery_uncertain", "record_id": row["key"]}, expected=row["revision"])
    for row in state.listing("wa_jobs", status="processing"):
        if row["payload"].get("claimed_at", 0) < time.time() - 900:
            state.put("wa_jobs", row["key"], {**row["payload"], "status": "pending" if row["payload"].get("attempts", 0) < 3 else "failed"}, expected=row["revision"])
    for row in state.listing("wa_jobs", status="pending", limit=100):
        key = row["key"]
        with _lock:
            if key in _running or len(_running) >= 2: continue
            _running.add(key)
        try: future = submit(run_job, key)
        except Exception:
            with _lock: _running.discard(key)
            raise
        def finished(_future, job_key=key):
            with _lock: _running.discard(job_key)
        future.add_done_callback(finished)
