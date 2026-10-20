"""Telegram and email intake for the shared customs quote record.

Telegram: explicitly link a chat with /link, then send and check a quote.
Polling and authenticated webhook delivery share a durable local job inbox.
Legacy business:<id> prefixes cannot override the company linked to a chat.

Email: IMAP inbox. A message is kept when the sender matches a business
`inbound_emails` entry (full address or @domain). The normalized record is
sent back with SMTP when SMTP_HOST is set, and copied to the business
Telegram chats when TELEGRAM_BOT_TOKEN is set.

Environment:
  TELEGRAM_BOT_TOKEN
  IMAP_HOST IMAP_USER IMAP_PASSWORD  (IMAP_PORT defaults to 993)
  SMTP_HOST SMTP_USER SMTP_PASSWORD  (SMTP_PORT defaults to 587)
  SMTP_FROM
"""

from __future__ import annotations

import email
import fcntl
import imaplib
import json
import os
import re
import secrets
import smtplib
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from customs import find_business, format_notice, load_businesses, to_customs_record
from quote_agent import compose_client_reply, parse_quote_smart

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
OFFSET_PATH = STATE_DIR / "telegram_offset.txt"
SEEN_PATH = STATE_DIR / "seen_email_ids.json"


def ingest_text(
    text: str,
    *,
    business_id: str | None = None,
    telegram_chat_id: str | None = None,
    email_from: str | None = None,
    business: dict | None = None,
) -> dict:
    from api.store import company_businesses

    if business is None:
        businesses = load_businesses() + company_businesses()
        business = find_business(
            businesses,
            business_id=business_id,
            telegram_chat_id=telegram_chat_id,
            email_from=email_from,
        )
    unassigned = False
    if business is None:
        unassigned = True
        business = {
            "id": "unassigned",
            "legal_name": "Unlinked chat",
            "home_country": "Nigeria",
            "default_currency": "USD",
            "default_incoterms": None,
        }
    quote = parse_quote_smart(text)
    record = to_customs_record(quote, business)
    from market import enrich

    record = enrich(record, business)
    from duty import estimate_duty

    record["duty_estimate"] = estimate_duty(text, record)
    notice = format_notice(record)
    if unassigned:
        notice += "\n\nThis chat is not linked yet. On the desk, copy /link and your company code, and send that here so the quote is filed under your agency."
    return {"notice": notice, "record": record, "business": business}


def _split_business_prefix(text: str) -> tuple[str | None, str]:
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("business:"):
        return lines[0].split(":", 1)[1].strip(), "\n".join(lines[1:]).strip()
    return None, text.strip()


def telegram_api(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
    data = json.dumps(payload or {}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=70) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Telegram {method} HTTP {exc.code}: {detail}") from exc
    body = json.loads(raw)
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram API error")
    return body


def send_telegram(chat_id: str, text: str, markup: dict | None = None) -> None:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Telegram sendMessage refused an empty message.")
    parts = []
    while len(text) > 3900:
        split = text.rfind("\n", 0, 3900)
        split = split if split > 0 else 3900
        parts.append(text[:split])
        text = text[split:].lstrip("\n")
    parts.append(text)
    for index, part in enumerate(parts):
        payload = {"chat_id": chat_id, "text": part}
        if markup and index == len(parts) - 1:
            payload["reply_markup"] = markup
        telegram_api("sendMessage", payload)


def _download_telegram_file(file_id: str) -> bytes:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    meta = telegram_api("getFile", {"file_id": file_id})
    path = (meta.get("result") or {}).get("file_path")
    if not path:
        raise RuntimeError("Telegram did not return a file path.")
    if int((meta.get("result") or {}).get("file_size") or 0) > 20 * 1024 * 1024:
        raise ValueError("The file is larger than 20 MB. Send a smaller file or paste the quote text.")
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60) as response:
        raw = response.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("The file is larger than 20 MB. Send a smaller file or paste the quote text.")
    return raw


_AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac")


def _audio_document(message: dict) -> dict | None:
    """An mp3 sent as a file arrives as a document, not as a voice note."""
    document = message.get("document") or {}
    name = (document.get("file_name") or "").lower()
    mime = (document.get("mime_type") or "").lower()
    if document and (mime.startswith("audio/") or name.endswith(_AUDIO_SUFFIXES)):
        return document
    return None


def _transcribe_audio(file_id: str, mime: str, caption: str) -> str:
    from quote_agent import gemini_media_text

    audio = _download_telegram_file(file_id)
    transcript = gemini_media_text(
        audio,
        mime or "audio/mpeg",
        "Transcribe this voice note. The speaker may use English or Nigerian Pidgin. "
        "Return only the words spoken, including every amount, port, and vendor.",
    )
    return f"{caption}\n{transcript}".strip()


def _media_text(message: dict) -> str:
    """Turn a voice note, photo, or PDF into text. Text messages pass through."""
    from quote_agent import gemini_media_text

    caption = message.get("caption") or ""
    voice = message.get("voice") or message.get("audio")
    if voice:
        return _transcribe_audio(voice["file_id"], voice.get("mime_type") or "audio/ogg", caption)
    audio_file = _audio_document(message)
    if audio_file:
        mime = audio_file.get("mime_type") or "audio/mpeg"
        return _transcribe_audio(audio_file["file_id"], mime, caption)
    photo = message.get("photo") or []
    if photo:
        image = _download_telegram_file(photo[-1]["file_id"])
        read = gemini_media_text(image, "image/jpeg", "Read every charge, port, vendor, date, and commodity on this quote image. Return plain text.")
        return f"{caption}\n{read}".strip()
    document = message.get("document") or {}
    if document:
        name = (document.get("file_name") or "").lower()
        mime = document.get("mime_type") or ""
        if not (name.endswith((".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webp")) or mime in {"application/pdf", "text/plain"} or mime.startswith("image/")):
            raise ValueError("Send a PDF, TXT, photo, or audio file. This file type is not supported.")
        data = _download_telegram_file(document["file_id"])
        if name.endswith(".txt") or mime == "text/plain":
            return f"{caption}\n{data.decode('utf-8', errors='replace')}".strip()
        if name.endswith(".pdf") or mime == "application/pdf":
            from api.exports import pdf_to_text

            text = pdf_to_text(data)
            if not text.strip():
                text = gemini_media_text(data, "application/pdf", "Extract the freight quote text, including charges and ports.")
            return f"{caption}\n{text}".strip()
        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            read = gemini_media_text(data, mime or "image/jpeg", "Read every charge, port, vendor, date, and commodity on this quote image. Return plain text.")
            return f"{caption}\n{read}".strip()
    return (message.get("text") or caption).strip()


def _dashboard_url() -> str | None:
    url = (os.environ.get("DASHBOARD_URL") or "").rstrip("/")
    if not url:
        callback = urllib.parse.urlparse(os.environ.get("PAYSTACK_CALLBACK_URL") or "")
        if callback.hostname not in {None, "localhost", "127.0.0.1", "::1"} and callback.path.rstrip("/") == "/billing":
            url = urllib.parse.urlunparse((callback.scheme, callback.netloc, "", "", "", ""))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    # The public homepage now owns '/'; Telegram should open the actual desk.
    path = parsed.path.rstrip("/") or "/desk"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _menu_keyboard() -> dict:
    rows = [
        [{"text": "New quote", "callback_data": "menu:new"}, {"text": "My status", "callback_data": "menu:status"}],
        [{"text": "Compare quotes", "callback_data": "menu:compare"}, {"text": "Help", "callback_data": "menu:help"}],
    ]
    if _dashboard_url():
        rows.append([{"text": "Open clearing desk", "url": _dashboard_url()}])
    return {"inline_keyboard": rows}


def _quote_keyboard(record_id: str, reviewed: bool = True) -> dict:
    rows = [[{"text": "Check details", "callback_data": f"review:{record_id}"}]]
    if reviewed:
        rows.extend([
            [{"text": "Download Client PDF", "callback_data": f"pdf:{record_id}"}, {"text": "Export to Excel", "callback_data": f"xlsx:{record_id}"}],
            [{"text": "Share to WhatsApp", "callback_data": f"wa:{record_id}"}, {"text": "Resolve Flags", "callback_data": f"flags:{record_id}"}],
            [{"text": "Request payment", "callback_data": f"pay:{record_id}"}, {"text": "Request clearance", "callback_data": f"clear:{record_id}"}],
        ])
    rows.append([{"text": "Correct quote", "callback_data": f"correct:{record_id}"}, {"text": "Compare quotes", "callback_data": "menu:compare"}])
    rows.append([{"text": "New quote", "callback_data": "menu:new"}])
    if _dashboard_url():
        rows.append([{"text": "Open clearing desk", "url": _dashboard_url()}])
    return {"inline_keyboard": rows}


def _chat_business(chat_id: str) -> dict | None:
    from api.store import company_businesses, using_cloud

    # Explicit workspace links take precedence over legacy file profiles.
    if using_cloud():
        from api.cloud_store import company_businesses as cloud_businesses
        businesses = cloud_businesses()
    else:
        businesses = company_businesses()
    return find_business(businesses + load_businesses(), telegram_chat_id=chat_id)


def _bind_chat(chat_id: str) -> str | None:
    """Read an existing link. Never attach an unknown chat automatically."""
    business = _chat_business(chat_id)
    return business["id"] if business else None


@contextmanager
def _chat_lock(chat_id: str):
    if not re.fullmatch(r"-?\d+", chat_id):
        raise ValueError("Invalid Telegram chat.")
    folder = STATE_DIR / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"telegram-{chat_id}.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _compare_ids(chat_id: str) -> list:
    from cache import get_json

    ids = get_json(f"compare:{chat_id}")
    return ids if isinstance(ids, list) else []


def _load_record(record_id: str, company_id: str | None = None) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id):
        return None
    from api.store import using_cloud
    from supabase_sync import get_quote

    if company_id and using_cloud():
        try:
            remote = get_quote(record_id, company_id)
            if remote:
                return remote
        except Exception:
            pass  # A locally saved quote remains usable while sync is unavailable.
    path = STATE_DIR / "records" / f"{record_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _authorized_record(chat_id: str, record_id: str) -> dict | None:
    business = _chat_business(chat_id)
    if not business:
        return None
    record = _load_record(record_id, business["id"])
    owner = (record or {}).get("company_id") or ((record or {}).get("business") or {}).get("id")
    if owner != business["id"]:
        return None
    source_chat = (record or {}).get("chat_id")
    if source_chat is not None and str(source_chat) != chat_id:
        return None
    if source_chat is None and record_id not in _compare_ids(chat_id):
        return None
    return {**record, "company_id": owner, "record_id": record_id}


def _route_key(record: dict) -> tuple:
    movement = record.get("movement") or {}
    return tuple(str((movement.get(key) or {}).get("location_name") or "").casefold() for key in ("origin", "destination"))


def _remember_compare(chat_id: str, record_id: str) -> None:
    from cache import set_json

    record = _authorized_record(chat_id, record_id)
    ids = []
    for item in _compare_ids(chat_id):
        previous = _authorized_record(chat_id, item)
        if item != record_id and previous and record and _route_key(previous) == _route_key(record):
            ids.append(item)
    set_json(f"compare:{chat_id}", (ids + [record_id])[-3:], 7 * 24 * 3600)


def _compare_text(chat_id: str) -> str:
    records = [_authorized_record(chat_id, rid) for rid in _compare_ids(chat_id)]
    records = [record for record in records if record]
    if len(records) < 2:
        return "Send at least two quotes for the same origin and destination, then use /compare. I keep up to three comparable quotes from this chat."
    rows = []
    for record in records:
        commercial = record.get("commercial") or {}
        landed = (((record.get("fx") or {}).get("cbn") or {}).get("NGN"))
        cash = f"NGN {landed:,.0f}" if landed is not None else "NGN estimate unavailable"
        rows.append(f"{commercial.get('vendor_name') or 'Vendor'} {commercial.get('quote_reference_id') or ''}\n  Quoted: {commercial.get('currency')} {commercial.get('total_amount'):,.2f}\n  Cash estimate: {cash}\n  Transit: {(record.get('movement') or {}).get('est_transit_days') or 'not provided'} days")
    return "Same-route comparison (planning estimates):\n\n" + "\n\n".join(rows)


def _load_dialog(chat_id: str) -> dict | None:
    from cache import get_json
    data = get_json(f"dialog:{chat_id}")
    return data if isinstance(data, dict) else None


def _save_dialog(chat_id: str, raw: str, **details) -> None:
    from cache import set_json
    set_json(f"dialog:{chat_id}", {"raw": raw, **details}, 24 * 3600)


def _clear_dialog(chat_id: str) -> None:
    from cache import delete
    delete(f"dialog:{chat_id}")


def _looks_like_new_quote(text: str) -> bool:
    amounts = re.findall(r"(?:₦|NGN|USD|\$)\s*[\d,]+|[\d,]{4,}\s*(?:NGN|USD|naira|dollars?)", text, re.I)
    return len(amounts) >= 2 or len(text) > 500


def _merge_follow_up(previous: str, reply: str) -> str:
    return f"{previous.rstrip()}\n\nFollow-up from the client:\n{reply.strip()}"


def _missing_details(record: dict) -> list[str]:
    movement = record.get("movement") or {}
    missing = [field for field in ("origin", "destination") if not (movement.get(field) or {}).get("location_name")]
    if not record.get("line_items") or float((record.get("commercial") or {}).get("total_amount") or 0) <= 0:
        missing.append("charges")
    return missing


def _reject_absurd(record: dict) -> str | None:
    commercial = record.get("commercial") or {}
    total = float(commercial.get("total_amount") or 0)
    fx = record.get("fx") or {}
    if commercial.get("currency") == "USD" and total >= 100_000 and not fx.get("mixed"):
        return "This quote is on hold: the USD total is unusually high. Reply with the freight in USD and local charges in NGN, or use /new for another quote."
    if float((fx.get("cbn") or {}).get("NGN") or 0) > 500_000_000:
        return "This quote is on hold: the NGN estimate is above 500 million. Check the currencies and resend the corrected amounts."
    return None


def _decide_action(text: str, record: dict, held: str | None) -> str:
    if held or record.get("agent_ready") is False:
        return "ask"
    low = text.lower()
    if any(word in low for word in ("pay ", "pay the", "transfer", "disburse", "send money")):
        return "pay"
    if any(word in low for word in ("clear the cargo", "clear cargo", "release the cargo", "file customs")):
        return "clear"
    return "publish"


def _notify_address(outcome: dict) -> str:
    return ((outcome.get("business") or {}).get("notify_email") or "").strip()


def _client_letter(client_text: str, outcome: dict, decision: str, held: str | None) -> str:
    return compose_client_reply(client_text, outcome["record"], decision, held)


def _act(chat_id: str, outcome: dict, decision: str, held: str | None, client_text: str = "") -> str:
    if decision in {"pay", "clear"}:
        from actions import attempt
        result = attempt(decision, outcome["record"], chat_id)
        notice = f"Review #{result['review_id']} is waiting in the desk’s Approvals queue. {result['note']}"
    else:
        notice = _client_letter(client_text, outcome, decision, held)
    reference = (outcome["record"].get("commercial") or {}).get("quote_reference_id") or "quote"
    if send_email(_notify_address(outcome), f"Quote {reference}", notice):
        return f"{notice}\n\nAn email copy was sent to your company’s notification address."
    return notice


def _telegram_notice(record: dict, *, full: bool = False) -> str:
    commercial = record.get("commercial") or {}
    movement = record.get("movement") or {}
    currency = commercial.get("currency") or "Currency missing"
    rows = [
        "Quote checked" if (record.get("desk_review") or {}).get("status") == "reviewed" else "Quote saved — ready to check",
        f"Vendor: {commercial.get('vendor_name') or 'Not provided'}",
        f"Reference: {commercial.get('quote_reference_id') or record.get('record_id')}",
        f"Route: {(movement.get('origin') or {}).get('location_name') or '?'} → {(movement.get('destination') or {}).get('location_name') or '?'}",
        f"Quoted total: {currency} {float(commercial.get('total_amount') or 0):,.2f}",
        "\nCharges:",
    ]
    items = record.get("line_items") or []
    rows.extend(f"• {item.get('description')}: {item.get('currency') or currency} {float(item.get('amount') or 0):,.2f}" for item in (items if full else items[:8]))
    if len(items) > 8 and not full:
        rows.append(f"Showing 8 of {len(items)} charge lines. The export includes all charges.")
    fx = record.get("fx") or {}
    ngn = (fx.get("cbn") or {}).get("NGN")
    if ngn is not None:
        rows.append(f"\nNGN planning estimate: {ngn:,.2f}")
    if fx.get("mixed"):
        rows.append("Mixed currencies: USD freight is kept separately from local NGN charges.")
    if record.get("sync_pending"):
        rows.append("Saved locally. Sync to the desk is pending; downloads in this chat remain available.")
    flags = record.get("extraction_flags") or []
    if flags:
        rows.append("\nExtraction notes:\n" + "\n".join(f"• {flag}" for flag in (flags if full else flags[:4])))
        if len(flags) > 4 and not full:
            rows.append(f"Showing 4 of {len(flags)} notes. Check details shows them all.")
    if full:
        rows.extend([f"\nValid until: {commercial.get('valid_until') or 'Not provided'}", f"Incoterms: {commercial.get('incoterms') or 'Not provided'}", f"Payment terms: {commercial.get('payment_terms') or 'Not provided'}"])
    rows.append("\nNext: choose a download or request desk approval." if record.get("desk_review") else "\nNext: check the route, amounts, and notes. Tap Check details before exporting. Use Correct quote to change something.")
    return "\n".join(rows)


def _welcome(chat_id: str, business: dict | None) -> None:
    if not business:
        send_telegram(chat_id, "Welcome to Clearing Desk.\n\n1. Sign in on the clearing desk.\n2. Open Connections and copy your /link command.\n3. Send that command here.\n\nOnce linked, send quote text, a PDF/TXT file, a photo, or a voice note. I will guide you through checking it before export.", _menu_keyboard())
        return
    send_telegram(chat_id, f"Linked to {business.get('legal_name') or business['id']}.\n\n1. Send a carrier quote (text, PDF/TXT, photo, or audio).\n2. Reply with any missing route or charge details.\n3. Check the quote, then download PDF/Excel or request desk approval.\n\n/new — start another quote\n/cancel — discard a draft\n/status — see your workspace and latest quote\n/compare — compare up to three same-route quotes\n/pay or /clear — request approval for the latest checked quote\n/settings — open your company settings\n/unlink — disconnect this chat", _menu_keyboard())


def _can_manage_chat(message: dict) -> bool:
    chat = message.get("chat") or {}
    if chat.get("type") not in {"group", "supergroup", "channel"}:
        return True
    user_id = (message.get("from") or {}).get("id")
    if not user_id:
        return False
    member = telegram_api("getChatMember", {"chat_id": chat["id"], "user_id": user_id})
    return (member.get("result") or {}).get("status") in {"creator", "administrator"}


def _latest_record(chat_id: str) -> dict | None:
    from cache import get_json
    latest = get_json(f"latest:{chat_id}") or {}
    return _authorized_record(chat_id, latest.get("record_id", ""))


def _status(chat_id: str, business: dict) -> None:
    from api.store import user_by_company
    account = user_by_company(business["id"])
    record = _latest_record(chat_id)
    rows = [f"Company: {business.get('legal_name') or business['id']}"]
    if account:
        rows.append(f"Parses left: {account['quota_remaining']}")
    if _load_dialog(chat_id):
        rows.append("A quote is waiting for details. Reply with the requested detail, or /cancel.")
    if record:
        rows.append(f"Latest quote: {(record.get('commercial') or {}).get('quote_reference_id') or record['record_id']}")
        rows.append("Checked" if record.get("desk_review") else "Waiting for your check")
    else:
        rows.append("No saved quote in this chat yet. Send a quote to get started.")
    send_telegram(chat_id, "\n".join(rows), _quote_keyboard(record["record_id"], bool(record.get("desk_review"))) if record else _menu_keyboard())


def _action_prompt(chat_id: str, record: dict, kind: str) -> None:
    if not record.get("desk_review") or _missing_details(record):
        send_telegram(chat_id, "Check this quote first, then request approval. No money has been sent and no cargo has been cleared.", _quote_keyboard(record["record_id"], False))
        return
    label = "payment" if kind == "pay" else "cargo clearance"
    commercial = record.get("commercial") or {}
    send_telegram(chat_id, f"Request {label} for {commercial.get('vendor_name') or 'this vendor'}?\n{commercial.get('currency')} {float(commercial.get('total_amount') or 0):,.2f}\nQuote: {record['record_id']}\n\nThis queues a person’s review on the desk. It does not execute a payment or clearance.", {"inline_keyboard": [[{"text": f"Queue {label} review", "callback_data": f"confirm_{kind}:{record['record_id']}"}], [{"text": "Cancel", "callback_data": "menu:status"}]]})


def handle_telegram_message(message: dict) -> None:
    chat_id = str((message.get("chat") or {}).get("id") or "")
    with _chat_lock(chat_id):
        _handle_telegram_message(message)


def _handle_telegram_message(message: dict) -> None:
    from api.store import consume, link_telegram, user_by_company
    from cache import get_json, set_json, delete

    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    business = _chat_business(chat_id)
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/start" and argument.startswith("co-"):
        command = "/link"
    if command == "/link":
        if not argument.strip():
            send_telegram(chat_id, "Copy the full /link command from Connections on your desk, for example /link co-abc123. No quote parse is used.")
            return
        if not _can_manage_chat(message):
            send_telegram(chat_id, "Only a group administrator can link this chat to a company.")
            return
        if business and business["id"] != argument.strip():
            send_telegram(chat_id, "This chat is already linked to another company. Use /unlink first, then send the new company’s /link command.")
            return
        try:
            linked = link_telegram(argument.strip(), chat_id)
        except ValueError as exc:
            send_telegram(chat_id, str(exc))
            return
        if not linked:
            send_telegram(chat_id, "That company code was not found. Copy it again from Connections on your desk.")
            return
        _clear_dialog(chat_id)
        _welcome(chat_id, _chat_business(chat_id))
        return
    if command in {"/start", "/help"} or text.lower() in {"hello", "hi", "help"}:
        _welcome(chat_id, business)
        return
    if not business:
        _welcome(chat_id, None)
        return
    if command in {"/new", "/cancel"} or text.lower() == "new quote":
        _clear_dialog(chat_id)
        if command != "/cancel":
            delete(f"latest:{chat_id}")
        send_telegram(chat_id, "Draft discarded. Your saved quotes are unchanged." if command == "/cancel" else "New quote started. Send the vendor, origin, destination, charges, and currencies, or attach a PDF/TXT, photo, or audio file.", _menu_keyboard())
        return
    if command in {"/status", "/settings"}:
        if command == "/settings" and _dashboard_url():
            send_telegram(chat_id, "Manage your company’s parallel rate, port risk, and parse allowance in Settings on the desk.", {"inline_keyboard": [[{"text": "Open workspace settings", "url": f"{_dashboard_url()}#settings"}], [{"text": "My status", "callback_data": "menu:status"}]]})
            return
        _status(chat_id, business)
        return
    if command == "/unlink":
        if _can_manage_chat(message):
            send_telegram(chat_id, f"Disconnect this chat from {business.get('legal_name') or business['id']}? Saved company quotes will remain on the desk.", {"inline_keyboard": [[{"text": "Disconnect chat", "callback_data": f"unlink:{business['id']}"}, {"text": "Cancel", "callback_data": "menu:status"}]]})
        else:
            send_telegram(chat_id, "Only a group administrator can disconnect this chat.")
        return
    if command == "/compare" or text.lower() == "compare":
        send_telegram(chat_id, _compare_text(chat_id), _menu_keyboard())
        return
    intent = "pay" if command == "/pay" or text.lower() in {"pay the trucker", "pay", "send money"} else "clear" if command == "/clear" or text.lower() in {"clear cargo", "clear the cargo", "release the cargo"} else None
    if intent:
        if _load_dialog(chat_id):
            send_telegram(chat_id, "A quote is waiting for details. Finish it or use /cancel before requesting approval for the latest saved quote.")
            return
        record = _latest_record(chat_id)
        if record:
            _action_prompt(chat_id, record, intent)
        else:
            send_telegram(chat_id, "Send and check a quote first. I need a specific quote before queuing a payment or clearance review.", _menu_keyboard())
        return
    if text.startswith("/"):
        send_telegram(chat_id, "That command is not supported. Use /help for available commands, /new for another quote, or /cancel to discard a draft.", _menu_keyboard())
        return
    message_id = str(message.get("message_id") or secrets.token_hex(6))
    cached = get_json(f"reply:{chat_id}:{message_id}")
    if cached and cached.get("company_id") == business["id"]:
        send_telegram(chat_id, cached["text"], cached.get("markup"))
        return
    record_id = f"tg-{chat_id}-{message_id}"
    existing = _authorized_record(chat_id, record_id)
    if existing:
        send_telegram(chat_id, _telegram_notice(existing), _quote_keyboard(record_id, bool(existing.get("desk_review"))))
        return
    dialog = _load_dialog(chat_id)
    if dialog and dialog.get("company_id") != business["id"]:
        _clear_dialog(chat_id)
        dialog = None
    account = user_by_company(business["id"])
    already_charged = bool(dialog and dialog.get("charged"))
    if account and not already_charged and account["quota_remaining"] < 1:
        send_telegram(chat_id, "Your parse allowance is used up. Add parses in Settings on the desk. You can still use /status and export saved, checked quotes.", _menu_keyboard())
        return
    if not text:
        send_telegram(chat_id, "I’m reading your file. I’ll show the extracted quote here, or tell you what needs fixing.")
        try:
            text = _media_text(message)
        except Exception:
            send_telegram(chat_id, "I could not read that attachment. Send a readable PDF/TXT, photo, or audio file up to 20 MB, or paste the quote text. Photo and audio reading need the media service to be configured and available. No parse was charged for this failed read.")
            return
    if not text.strip():
        send_telegram(chat_id, "No readable quote text was found. Paste the vendor, route, charges, and currencies, or try another file. No parse was charged.")
        return
    requested_business, quote_text = _split_business_prefix(text)
    if requested_business and requested_business != business["id"]:
        send_telegram(chat_id, "That quote names a different company. I only file quotes under the company linked to this chat. Use /status to check your link.")
        return
    if dialog and dialog.get("raw"):
        missing = dialog.get("missing") or []
        if not missing and re.search(r"(?:NGN|USD|₦|\$)\s*[\d,]+", quote_text, re.I):
            send_telegram(chat_id, "For a price correction, use /new and send the full corrected quote. I won’t append new prices to the old charges. Your saved quote is unchanged.")
            return
        if missing and missing[0] in {"origin", "destination"} and len(quote_text.splitlines()) == 1 and not re.search(r"origin|destination|charges|freight|NGN|USD|\$|₦", quote_text, re.I):
            quote_text = f"{missing[0].title()}: {quote_text}"
        quote_text = _merge_follow_up(dialog["raw"], quote_text)
    send_telegram(chat_id, "I’m checking the route, charges, and currencies. I’ll ask for any missing detail next.")
    outcome = ingest_text(quote_text, business_id=business["id"], telegram_chat_id=chat_id, business=business)
    record = outcome["record"]
    commercial = record.get("commercial") or {}
    movement = record.get("movement") or {}
    priced = bool(record.get("line_items")) and float(commercial.get("total_amount") or 0) > 0
    meaningful = priced or commercial.get("vendor_name") or any((movement.get(field) or {}).get("location_name") for field in ("origin", "destination"))
    if not meaningful:
        send_telegram(chat_id, "I couldn’t find a freight quote in that message. Send the vendor, origin, destination, and priced charges with their currencies, or use /help. No parse was charged.", _menu_keyboard())
        return
    if account and priced and not already_charged:
        try:
            consume(account["id"], 1)
        except PermissionError:
            send_telegram(chat_id, "Your parse allowance was used by another request. Add parses on the desk and send the quote again.")
            return
    missing = _missing_details(record)
    held = _reject_absurd(record)
    if held or missing or record.get("agent_ready") is False:
        _save_dialog(chat_id, quote_text, company_id=business["id"], charged=bool(account and priced) or already_charged, missing=missing)
        question = held or (f"What is the {missing[0]}? Reply with the city or port name." if missing and missing[0] in {"origin", "destination"} else "Send the priced charges and their currencies, for example Freight: NGN 150,000.")
        reply = f"I’ve kept this quote and need one more detail.\n\n{question}\n\nReply here to continue this quote. /new starts another; /cancel discards this draft. Replies completing this draft do not use another parse."
        markup = _menu_keyboard()
    else:
        record.update({"record_id": record_id, "source_text": quote_text, "chat_id": chat_id})
        _store_record(record, record_id, chat_id=chat_id, telegram_user_id=str((message.get("from") or {}).get("id") or ""))
        _clear_dialog(chat_id)
        set_json(f"latest:{chat_id}", {"record_id": record_id}, 30 * 24 * 3600)
        _remember_compare(chat_id, record_id)
        reply, markup = _telegram_notice(record), _quote_keyboard(record_id, False)
    # Cache the result before sending so a Telegram redelivery cannot charge twice.
    set_json(f"reply:{chat_id}:{message_id}", {"company_id": business["id"], "text": reply, "markup": markup}, 24 * 3600)
    send_telegram(chat_id, reply, markup)


def _send_file(chat_id: str, filename: str, data: bytes, caption: str) -> None:
    import httpx
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    response = httpx.post(f"https://api.telegram.org/bot{token}/sendDocument", data={"chat_id": chat_id, "caption": caption[:900]}, files={"document": (filename, data)}, timeout=60)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram could not send the file. Try the download again.")


def _handle_callback(callback: dict) -> None:
    chat_id = str((callback.get("message") or {}).get("chat", {}).get("id") or "")
    if not chat_id:
        return
    if not callback.get("_answered"):
        try:
            telegram_api("answerCallbackQuery", {"callback_query_id": callback.get("id")})
        except Exception:
            pass  # An expired spinner must not discard a valid action.
    with _chat_lock(chat_id):
        try:
            _callback(callback, chat_id)
        except Exception as exc:
            print(f"[intake] callback failed: {type(exc).__name__}")
            send_telegram(chat_id, "I couldn’t complete that action. Your saved quote is still on the desk. Try again, or use /status to reopen its latest buttons.")


def _callback(callback: dict, chat_id: str) -> None:
    from cache import delete, get_json, set_json
    from api.exports import build_pdf, build_xlsx

    data = callback.get("data") or ""
    actor_message = {"chat": callback["message"]["chat"], "from": callback.get("from") or {}}
    if data == "compare":
        data = "menu:compare"  # Existing keyboards remain usable.
    if data.startswith("menu:"):
        command = data.partition(":")[2]
        if command in {"new", "status", "compare", "help"}:
            _handle_telegram_message({**actor_message, "text": f"/{command}"})
        return
    action, _, rest = data.partition(":")
    if action == "unlink":
        business = _chat_business(chat_id)
        if not business or business["id"] != rest or not _can_manage_chat(actor_message):
            send_telegram(chat_id, "That disconnect request is no longer valid, or you don’t manage this chat. Use /status.")
            return
        from api.store import unlink_telegram
        unlink_telegram(chat_id)
        path = ROOT / "businesses.json"
        if path.exists():
            profiles = json.loads(path.read_text(encoding="utf-8"))
            for profile in profiles.get("businesses") or []:
                profile["telegram_chat_ids"] = [item for item in profile.get("telegram_chat_ids") or [] if str(item) != chat_id]
            path.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")
        for key in ("dialog", "latest", "compare"):
            delete(f"{key}:{chat_id}")
        send_telegram(chat_id, "Chat disconnected. Saved company quotes remain on the desk. Copy another /link command from Connections when you’re ready.")
        return
    record_id = rest.partition(":")[0] if action == "rf" else rest
    record = _authorized_record(chat_id, record_id)
    if not record:
        send_telegram(chat_id, "That quote is unavailable in this chat. Use /status for your latest quote or send a new one.", _menu_keyboard())
        return
    business_name = (record.get("business") or {}).get("legal_name") or "Clearing desk"
    if action == "correct":
        raw = record.get("source_text")
        if not raw:
            send_telegram(chat_id, "This older quote has no saved source text. Use /new and send its corrected text or file.")
            return
        _save_dialog(chat_id, raw, company_id=record["company_id"], charged=True, missing=[])
        send_telegram(chat_id, "Reply with the corrected detail, for example Destination: Houston. For a price correction, send the complete corrected quote with /new so old charges are not combined. This correction creates a new quote; the original stays saved. /cancel stops the correction.")
        return
    if action == "review":
        send_telegram(chat_id, _telegram_notice(record, full=True), {"inline_keyboard": [[{"text": "Mark checked", "callback_data": f"checked:{record_id}"}], [{"text": "Correct quote", "callback_data": f"correct:{record_id}"}]]})
        return
    if action == "checked":
        if _missing_details(record) or _reject_absurd(record):
            send_telegram(chat_id, "This quote still needs corrected details. Use Correct quote or send a new quote.", _quote_keyboard(record_id, False))
            return
        first_check = not record.get("desk_review")
        record["desk_review"] = {"status": "reviewed", "reviewed_by": f"telegram:{(callback.get('from') or {}).get('id') or chat_id}", "reviewed_at": datetime.now(timezone.utc).isoformat()}
        _store_record(record, record_id, chat_id=chat_id)
        send_telegram(chat_id, "Quote checked and saved. Download a client file below. A payment or clearance still needs a separate request and approval on the desk.", _quote_keyboard(record_id, True))
        if first_check and os.environ.get("SMTP_HOST"):
            from workers import submit
            submit(_finish_quote, chat_id, {"record": record, "business": _chat_business(chat_id)}, "publish", None, record.get("source_text") or "", record, record_id, "")
        return
    if not record.get("desk_review"):
        send_telegram(chat_id, "Check this quote before exporting or requesting an approval.", _quote_keyboard(record_id, False))
        return
    if action in {"pay", "clear"}:
        _action_prompt(chat_id, record, action)
    elif action in {"confirm_pay", "confirm_clear"}:
        from actions import attempt
        from api.store import get_review
        kind = action.removeprefix("confirm_")
        key = f"action:{record_id}:{kind}"
        previous = get_json(key)
        existing = get_review(previous["review_id"], record["company_id"]) if previous else None
        if existing and existing["status"] != "rejected":
            send_telegram(chat_id, f"Review #{existing['id']} already exists and is {existing['status']}. Check Approvals on the desk. No duplicate request was created.")
            return
        result = attempt(kind, record, chat_id)
        set_json(key, {"review_id": result["review_id"]}, 30 * 24 * 3600)
        send_telegram(chat_id, f"Review #{result['review_id']} is waiting in Approvals on the desk. {result['note']}", _quote_keyboard(record_id, True))
    elif action == "pdf":
        _send_file(chat_id, f"{record_id}.pdf", build_pdf([record], business_name), "Checked client quote PDF")
    elif action == "xlsx":
        _send_file(chat_id, f"{record_id}.xlsx", build_xlsx([record], business_name), "Checked quote spreadsheet")
    elif action == "wa":
        summary = format_notice(record)[:1500]
        share = urllib.parse.quote(summary)
        while len(share) > 3400:
            summary = summary[:len(summary) // 2]
            share = urllib.parse.quote(summary)
        send_telegram(chat_id, f"Open this link to choose a WhatsApp recipient and send the quote:\nhttps://wa.me/?text={share}")
    elif action == "flags":
        from desk_ops import TELEGRAM_CODES, detect_operational_flags
        code_by_action = {value: key for key, value in TELEGRAM_CODES.items()}
        buttons = [[{"text": option["label"], "callback_data": f"rf:{record_id}:{code_by_action[(flag['flag_id'], option['id'])]}"} for option in flag["options"]] for flag in detect_operational_flags(record)]
        send_telegram(chat_id, "Choose how to resolve each flag. Changes require another quote check." if buttons else "No open operational flags were found on this quote.", {"inline_keyboard": buttons} if buttons else _quote_keyboard(record_id, True))
    elif action == "rf":
        from desk_ops import TELEGRAM_CODES, detect_operational_flags, resolve_flag
        pair = TELEGRAM_CODES.get(rest.rpartition(":")[2])
        if not pair:
            send_telegram(chat_id, "That flag choice is no longer available. Open Resolve Flags again.")
            return
        if pair[0] not in {flag["flag_id"] for flag in detect_operational_flags(record)}:
            send_telegram(chat_id, "That flag is already resolved or no longer applies. Use /status to reopen the current quote.")
            return
        if pair == ("uncapped_local_access", "cap_50000") and (record.get("commercial") or {}).get("currency") != "NGN":
            send_telegram(chat_id, "This cap is in NGN, but the quote is in another currency. Send a corrected quote with /new and an explicit currency split before applying a naira cap. No charges were changed.")
            return
        result = resolve_flag(record, pair[0], pair[1], actor=f"telegram:{chat_id}")
        _store_record(record, record_id, chat_id=chat_id)
        send_telegram(chat_id, f"{result['note']}. Check the updated quote before exporting again.", _quote_keyboard(record_id, False))
    else:
        send_telegram(chat_id, "That action is not supported. Use /status to get current buttons.")


def _finish_quote(chat_id, outcome, decision, held, quote_text, record, record_id, telegram_user_id) -> None:
    """Email an already saved, checked quote without delaying chat interaction."""
    try:
        address = _notify_address(outcome)
        if address and send_email(address, f"Checked quote {(record.get('commercial') or {}).get('quote_reference_id') or record_id}", _client_letter(quote_text, outcome, decision, held)):
            send_telegram(chat_id, "An email copy was sent to your company’s notification address.")
        elif address and os.environ.get("SMTP_HOST"):
            send_telegram(chat_id, "The quote is saved, but the email copy could not be sent. Downloads are still available here; check the email connection on the desk.")
    except Exception as exc:
        print(f"[intake] checked-quote email failed: {type(exc).__name__}")


def process_telegram_update(update: dict) -> bool:
    callback = update.get("callback_query")
    message = update.get("message") or update.get("channel_post") or {}
    chat_id = str(((callback or {}).get("message") or message).get("chat", {}).get("id") or "")
    try:
        if callback:
            _handle_callback(callback)
        elif chat_id and any(message.get(field) for field in ("text", "caption", "voice", "audio", "photo", "document")):
            handle_telegram_message(message)
        return True
    except Exception as exc:
        print(f"[intake] Telegram update failed: {type(exc).__name__}")
        if chat_id:
            try:
                send_telegram(chat_id, "I couldn’t finish that request. Use /status to check whether it was saved before sending it again.")
                return True
            except Exception:
                pass
        return False


def poll_telegram_once() -> int:
    from cache import get_text, set_text
    from telegram_jobs import enqueue, schedule_pending

    schedule_pending()
    saved = get_text("tg:offset")
    offset = int(saved) if saved and saved.isdigit() else int(OFFSET_PATH.read_text().strip() or "0") if OFFSET_PATH.exists() else 0
    body = telegram_api("getUpdates", {"timeout": 25, "offset": offset, "allowed_updates": ["message", "channel_post", "callback_query"]})
    updates = body.get("result") or []
    for update in updates:
        # Persist before acknowledging the update to Telegram. A restart can resume it.
        enqueue(update)
        callback = update.get("callback_query")
        if callback:
            try:
                telegram_api("answerCallbackQuery", {"callback_query_id": callback["id"]})
            except Exception:
                pass
        set_text("tg:offset", str(int(update["update_id"]) + 1))
    schedule_pending()
    return len(updates)


def _imap_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def send_email(to_address: str, subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    if not host or not to_address:
        return False
    message = EmailMessage()
    message["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=8)
        else:
            smtp = smtplib.SMTP(host, port, timeout=8)
            smtp.starttls()
        with smtp:
            user = os.environ.get("SMTP_USER")
            password = os.environ.get("SMTP_PASSWORD")
            if user and password:
                smtp.login(user, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        print(f"[intake] email not sent: {exc}")
        return False
    return True


def poll_email_once() -> int:
    host = os.environ.get("IMAP_HOST")
    user = os.environ.get("IMAP_USER")
    password = os.environ.get("IMAP_PASSWORD")
    if not (host and user and password):
        return 0
    from cache import get_json, set_json

    seen_raw = get_json("mail:seen")
    if isinstance(seen_raw, list):
        seen = set(seen_raw)
    else:
        seen = set(json.loads(SEEN_PATH.read_text())) if SEEN_PATH.exists() else set()
    handled = 0
    client = imaplib.IMAP4_SSL(host, int(os.environ.get("IMAP_PORT", "993")))
    try:
        client.login(user, password)
        client.select("INBOX")
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for msg_id in data[0].split():
            key = msg_id.decode()
            if key in seen:
                continue
            status, fetched = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            sender = parseaddr(msg.get("From") or "")[1]
            subject = msg.get("Subject") or "Freight quote"
            own = {
                (os.environ.get("SMTP_FROM") or "").lower(),
                (os.environ.get("SMTP_USER") or "").lower(),
                (os.environ.get("IMAP_USER") or "").lower(),
            }
            if sender.lower() in own:
                seen.add(key)
                continue
            body = _imap_body(msg)
            try:
                outcome = ingest_text(f"{subject}\n{body}", email_from=sender)
            except LookupError:
                seen.add(key)
                continue
            record = outcome["record"]
            held = _reject_absurd(record)
            decision = _decide_action(body, record, held)
            letter = _client_letter(body, outcome, decision, held)
            business = outcome.get("business") or find_business(load_businesses(), email_from=sender)
            reference = (record.get("commercial") or {}).get("quote_reference_id") or "quote"
            if business and business.get("notify_email"):
                send_email(business["notify_email"], f"Quote {reference}".strip(), letter)
            if os.environ.get("TELEGRAM_BOT_TOKEN") and business:
                for chat_id in business.get("telegram_chat_ids") or []:
                    send_telegram(str(chat_id), "A quote arrived by email. I replied by email.")
            if decision == "ask":
                seen.add(key)
                handled += 1
                continue
            _store_record(record, f"mail-{key}")
            seen.add(key)
            handled += 1
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    set_json("mail:seen", sorted(seen)[-500:])
    return handled


def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        temporary = handle.name
    os.replace(temporary, path)


def _store_record(record: dict, name: str, *, chat_id: str | None = None, telegram_user_id: str | None = None) -> None:
    company_id = (record.get("business") or {}).get("id")
    if company_id:
        record["company_id"] = company_id
    record["record_id"] = name
    if chat_id is not None:
        record["chat_id"] = str(chat_id)
    if telegram_user_id:
        record["telegram_user_id"] = telegram_user_id
    path = STATE_DIR / "records" / f"{name}.json"
    remote = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    record["sync_pending"] = remote
    _write_record(path, record)
    try:
        from supabase_sync import sync_quote

        saved = sync_quote({**record, "sync_pending": False}, name, chat_id=chat_id, telegram_user_id=telegram_user_id)
        if not remote or saved:
            record["sync_pending"] = False
            _write_record(path, record)
    except Exception as exc:  # noqa: BLE001 — a local quote still stands if Supabase is down
        print(f"[intake] Supabase sync pending: {type(exc).__name__}")


def _retry_pending_record() -> None:
    from supabase_sync import sync_quote
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return
    for path in (STATE_DIR / "records").glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not record.get("sync_pending"):
                continue
            chat_id = record.get("chat_id")
            # Telegram records serialize edits and retries using the same chat lock.
            with _chat_lock(str(chat_id)) if chat_id is not None else _chat_lock("0"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if not record.get("sync_pending"):
                    continue
                saved = sync_quote({**record, "sync_pending": False}, path.stem, chat_id=chat_id, telegram_user_id=record.get("telegram_user_id"))
                if saved:
                    record["sync_pending"] = False
                    _write_record(path, record)
            return  # Bound each retry so it cannot occupy a worker indefinitely.
        except Exception as exc:
            print(f"[intake] sync retry deferred: {type(exc).__name__}")
            return


_LOCK_HANDLE = None


def configure_telegram_commands() -> None:
    commands = [
        ("start", "Link your company and get started"),
        ("help", "Quote formats and available actions"),
        ("new", "Start a new quote"),
        ("cancel", "Discard the current draft"),
        ("status", "Your company, allowance, and latest quote"),
        ("compare", "Compare up to three same-route quotes"),
        ("pay", "Request payment approval for the latest checked quote"),
        ("clear", "Request clearance approval for the latest checked quote"),
        ("settings", "Workspace status and desk settings"),
        ("link", "Connect using the code from your desk"),
        ("unlink", "Disconnect this chat from its company"),
    ]
    telegram_api("setMyCommands", {"commands": [{"command": name, "description": description} for name, description in commands]})


def _lock_intake() -> None:
    import fcntl

    global _LOCK_HANDLE
    STATE_DIR.mkdir(exist_ok=True)
    handle = (STATE_DIR / "intake.lock").open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another quote intake is already running. Stop that one before starting a second.")
    handle.write(str(os.getpid()))
    handle.flush()
    _LOCK_HANDLE = handle


def main() -> None:
    _lock_intake()
    mode = os.environ.get("TELEGRAM_DELIVERY_MODE", "polling").lower()
    if mode not in {"polling", "webhook"}:
        raise ValueError("TELEGRAM_DELIVERY_MODE must be polling or webhook.")
    if mode == "webhook" and not os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        raise ValueError("Set TELEGRAM_WEBHOOK_SECRET before enabling webhook mode.")
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            configure_telegram_commands()
        except Exception as exc:
            print(f"[intake] command menu setup failed: {type(exc).__name__}")
    print(f"Quote intake running. Telegram delivery: {mode}. Email checks every minute.")
    last_mail = 0.0
    sync_job = None
    while True:
        from telegram_jobs import schedule_pending
        try:
            schedule_pending()
        except Exception as exc:
            print(f"[intake] job recovery deferred: {type(exc).__name__}")
        retry_delay = 0
        try:
            if os.environ.get("TELEGRAM_BOT_TOKEN") and mode == "polling":
                poll_telegram_once()
            else:
                time.sleep(1)
        except Exception as exc:
            message = str(exc)
            if "409" in message or "Conflict" in message:
                print("[intake] Telegram delivery conflict. Stop the duplicate poller, or set TELEGRAM_DELIVERY_MODE=webhook. No webhook was deleted.")
            else:
                print(f"[intake] Telegram poll failed: {type(exc).__name__}")
            retry_delay = 5
        if time.time() - last_mail > 60:
            try:
                poll_email_once()
            except Exception as exc:
                print(f"[intake] email check failed: {type(exc).__name__}")
            if sync_job is None or sync_job.done():
                from workers import submit
                sync_job = submit(_retry_pending_record)
            last_mail = time.time()
        if retry_delay:
            time.sleep(retry_delay)


if __name__ == "__main__":
    main()
