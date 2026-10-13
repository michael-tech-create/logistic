"""Telegram and email intake for the shared customs quote record.

Telegram: long-poll getUpdates. Send the bot a quote. First line may be
`business:<id>` when the chat is not already mapped in businesses.json.

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
import imaplib
import json
import os
import re
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
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
) -> dict:
    from api.store import company_businesses

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
    with urllib.request.urlopen(request, timeout=70) as response:
        body = json.loads(response.read().decode())
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram API error")
    return body


def send_telegram(chat_id: str, text: str, markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if markup:
        payload["reply_markup"] = markup
    telegram_api("sendMessage", payload)


def _download_telegram_file(file_id: str) -> bytes:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    meta = telegram_api("getFile", {"file_id": file_id})
    path = (meta.get("result") or {}).get("file_path")
    if not path:
        raise RuntimeError("Telegram did not return a file path.")
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60) as response:
        return response.read()


def _media_text(message: dict) -> str:
    """Turn a voice note, photo, or PDF into text. Text messages pass through."""
    from quote_agent import gemini_media_text

    caption = message.get("caption") or ""
    voice = message.get("voice") or message.get("audio")
    if voice:
        audio = _download_telegram_file(voice["file_id"])
        mime = voice.get("mime_type") or "audio/ogg"
        transcript = gemini_media_text(
            audio,
            mime,
            "Transcribe this voice note. The speaker may use English or Nigerian Pidgin. Return only the words spoken.",
        )
        return f"{caption}\n{transcript}".strip()
    photo = message.get("photo") or []
    if photo:
        image = _download_telegram_file(photo[-1]["file_id"])
        read = gemini_media_text(image, "image/jpeg", "Read every charge, port, vendor, date, and commodity on this quote image. Return plain text.")
        return f"{caption}\n{read}".strip()
    document = message.get("document") or {}
    if document:
        name = (document.get("file_name") or "").lower()
        mime = document.get("mime_type") or ""
        data = _download_telegram_file(document["file_id"])
        if name.endswith(".pdf") or mime == "application/pdf":
            from api.exports import pdf_to_text

            text = pdf_to_text(data)
            if len(text) < 40:
                text = gemini_media_text(data, "application/pdf", "Extract the freight quote text, including charges and ports.")
            return f"{caption}\n{text}".strip()
        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            read = gemini_media_text(data, mime or "image/jpeg", "Read every charge, port, vendor, date, and commodity on this quote image. Return plain text.")
            return f"{caption}\n{read}".strip()
    return (message.get("text") or caption).strip()


def _quote_keyboard(record_id: str) -> dict:
    return {"inline_keyboard": [
        [
            {"text": "Download Client PDF", "callback_data": f"pdf:{record_id}"},
            {"text": "Export to Excel", "callback_data": f"xlsx:{record_id}"},
        ],
        [
            {"text": "Share to WhatsApp", "callback_data": f"wa:{record_id}"},
            {"text": "Resolve Flags", "callback_data": f"flags:{record_id}"},
        ],
        [{"text": "Compare quotes", "callback_data": "compare"}],
    ]}


def _compare_ids(chat_id: str) -> list:
    from cache import get_json

    ids = get_json(f"compare:{chat_id}")
    return ids if isinstance(ids, list) else []


def _remember_compare(chat_id: str, record_id: str) -> None:
    from cache import set_json

    ids = [item for item in _compare_ids(chat_id) if item != record_id]
    ids.append(record_id)
    set_json(f"compare:{chat_id}", ids[-3:], 7 * 24 * 3600)


def _load_record(record_id: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id):
        return None
    path = STATE_DIR / "records" / f"{record_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_text(chat_id: str) -> str:
    ids = _compare_ids(chat_id)
    rows = []
    for record_id in ids:
        record = _load_record(record_id)
        if not record:
            continue
        commercial = record.get("commercial") or {}
        movement = record.get("movement") or {}
        landed = ((record.get("fx") or {}).get("cbn") or {}).get("NGN")
        rows.append(
            f"{commercial.get('vendor_name') or 'Vendor'} {commercial.get('quote_reference_id') or ''}\n"
            f"  Landed NGN {landed or 0:,.0f} · transit {movement.get('est_transit_days') or 'n/a'} days\n"
            f"  Free days {(record.get('demurrage') or {}).get('free_days', 'n/a')} · "
            f"buffer NGN {((record.get('demurrage') or {}).get('buffer_ngn') or 0):,.0f}\n"
            f"  Flags {len(record.get('extraction_flags') or [])}"
        )
    if not rows:
        return "No quotes are in the comparison yet. Send up to 3 quotes, then tap Compare."
    return "Comparison of the last quotes in this chat:\n\n" + "\n\n".join(rows)


def _send_file(chat_id: str, filename: str, data: bytes, caption: str) -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data={"chat_id": chat_id, "caption": caption[:900]},
        files={"document": (filename, data)},
        timeout=60,
    )
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram could not send the file.")


def _handle_callback(callback: dict) -> None:
    from api.exports import build_pdf, build_xlsx

    chat_id = str((callback.get("message") or {}).get("chat", {}).get("id"))
    data = callback.get("data") or ""
    telegram_api("answerCallbackQuery", {"callback_query_id": callback.get("id")})
    if data == "compare":
        send_telegram(chat_id, _compare_text(chat_id))
        return
    action, _, rest = data.partition(":")
    if action == "rf":
        record_id, _, _code = rest.partition(":")
    else:
        record_id = rest
    record = _load_record(record_id)
    if record is None:
        send_telegram(chat_id, "That quote is no longer on the desk.")
        return
    business = (record.get("business") or {}).get("legal_name") or "Clearing desk"
    if action == "pdf":
        _send_file(chat_id, f"{record_id}.pdf", build_pdf([record], business), "Client quote PDF")
    elif action == "xlsx":
        _send_file(chat_id, f"{record_id}.xlsx", build_xlsx([record], business), "Quote spreadsheet")
    elif action == "wa":
        share = urllib.parse.quote((format_notice(record))[:1500])
        send_telegram(chat_id, f"https://wa.me/?text={share}")
    elif action == "flags":
        from desk_ops import TELEGRAM_CODES, detect_operational_flags

        buttons = []
        code_by_action = {value: key for key, value in TELEGRAM_CODES.items()}
        for flag in detect_operational_flags(record):
            row = []
            for option in flag["options"]:
                code = code_by_action[(flag["flag_id"], option["id"])]
                row.append({"text": option["label"], "callback_data": f"rf:{record_id}:{code}"})
            buttons.append(row)
        if buttons:
            send_telegram(chat_id, "Choose how to close each open flag.", {"inline_keyboard": buttons})
        else:
            send_telegram(chat_id, "This quote has no open operational flag.")
    elif action == "rf":
        from desk_ops import TELEGRAM_CODES, resolve_flag, save_record
        from api.exports import build_pdf

        code = data.split(":")[-1]
        pair = TELEGRAM_CODES.get(code)
        if pair is None:
            send_telegram(chat_id, "That flag action is not recognized.")
            return
        try:
            result = resolve_flag(record, pair[0], pair[1], actor=f"telegram:{chat_id}")
        except ValueError as exc:
            send_telegram(chat_id, str(exc))
            return
        save_record(record_id, record, chat_id=chat_id)
        send_telegram(chat_id, result["note"])
        if result["recalculated"]:
            _send_file(chat_id, f"{record_id}.pdf", build_pdf([record], business), "Updated client quote PDF")


def _bind_chat(chat_id: str) -> str | None:
    """Attach this chat to the only company when none is linked yet."""
    path = ROOT / "businesses.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    businesses = data.get("businesses") or []
    if len(businesses) != 1:
        return None
    business = businesses[0]
    chats = [str(item) for item in business.get("telegram_chat_ids") or []]
    if chat_id not in chats:
        chats.append(chat_id)
        business["telegram_chat_ids"] = chats
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return business["id"]


def _load_dialog(chat_id: str) -> dict | None:
    from cache import get_json

    data = get_json(f"dialog:{chat_id}")
    return data if isinstance(data, dict) else None


def _save_dialog(chat_id: str, raw: str) -> None:
    from cache import set_json

    set_json(f"dialog:{chat_id}", {"raw": raw}, 24 * 3600)


def _clear_dialog(chat_id: str) -> None:
    from cache import delete

    delete(f"dialog:{chat_id}")


def _looks_like_new_quote(text: str) -> bool:
    amounts = re.findall(r"(?:₦|NGN|USD|\$)\s*[\d,]+|[\d,]{4,}\s*(?:NGN|USD|naira|dollars?)", text, re.I)
    return len(amounts) >= 2 or len(text) > 500


def _merge_follow_up(previous: str, reply: str) -> str:
    return f"{previous.rstrip()}\n\nFollow-up from the client:\n{reply.strip()}"


def _reject_absurd(record: dict) -> str | None:
    commercial = record.get("commercial") or {}
    total = float(commercial.get("total_amount") or 0)
    currency = (commercial.get("currency") or "").upper()
    fx_ngn = float((((record.get("fx") or {}).get("cbn") or {}).get("NGN")) or 0)
    mixed = bool((record.get("fx") or {}).get("mixed"))
    if currency == "USD" and total >= 100_000 and not mixed:
        return (
            "I am holding this quote. A total above USD 100,000 was not split into dollar freight and naira local charges. "
            "Reply with which amounts are NGN and which are USD. I will add that to the quote I already have."
        )
    if fx_ngn > 500_000_000:
        return (
            "I am holding this quote. The naira figure is above 500 million, so I will not publish it. "
            "Reply with the ocean freight in USD and the local charges in NGN."
        )
    return None


def _decide_action(text: str, record: dict, held: str | None) -> str:
    """Pick one next step. pay and clear stay blocked until a bank or customs rail exists."""
    low = text.lower()
    asks_money = any(word in low for word in ("pay ", "pay the", "transfer", "disburse", "send money"))
    asks_clear = any(word in low for word in ("clear the cargo", "clear cargo", "release the cargo", "file customs"))
    if held or record.get("agent_ready") is False:
        return "ask"
    if asks_money:
        return "pay"
    if asks_clear:
        return "clear"
    return "publish"


def _notify_address(outcome: dict) -> str:
    business = outcome.get("business") or {}
    return (business.get("notify_email") or "").strip()


def _client_letter(client_text: str, outcome: dict, decision: str, held: str | None) -> str:
    return compose_client_reply(client_text, outcome["record"], decision, held)


def _act(chat_id: str, outcome: dict, decision: str, held: str | None, client_text: str = "") -> str:
    """Send the email when SMTP is configured, then return the Telegram reply."""
    if decision in {"pay", "clear"}:
        from actions import attempt

        result = attempt(decision, outcome["record"], chat_id)
        if result["done"]:
            notice = result["note"]
        else:
            notice = (
                f"I could not {decision} this automatically. {result['note']} "
                f"Review {result['review_id']} is on the desk for a person."
            )
    else:
        notice = _client_letter(client_text, outcome, decision, held)
    address = _notify_address(outcome)
    reference = ((outcome["record"].get("commercial") or {}).get("quote_reference_id")) or "quote"
    mailed = send_email(address, f"Quote {reference}".strip(), notice)
    if mailed:
        return f"I sent the quote by email to {address}."
    if decision == "ask":
        follow = "" if held else " Reply with the missing piece and I will add it to this quote."
        return (held or "I still need a few details before I can email this quote.") + follow
    return ""


def handle_telegram_message(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id"))
    text = message.get("text") or ""
    (ROOT / "state").mkdir(exist_ok=True)
    bound = _bind_chat(chat_id)
    if text.strip().lower() in {"/compare", "compare"}:
        send_telegram(chat_id, _compare_text(chat_id))
        return
    if not text:
        try:
            text = _media_text(message)
        except Exception as exc:  # noqa: BLE001 — tell the chat instead of dying on one file
            send_telegram(chat_id, f"I could not read that file. {exc}")
            return
    (ROOT / "state" / "last_quote.txt").write_text(text, encoding="utf-8")
    if text.lower().startswith("/link "):
        from api.store import link_telegram
        linked = link_telegram(text.split(" ", 1)[1], chat_id)
        send_telegram(chat_id, f"Linked to {linked['legal_name']}." if linked else "That company code was not found.")
        return
    if text.strip() in {"/start", "/help"}:
        company = bound or "your company"
        send_telegram(
            chat_id,
            f"This chat is linked to {company}. Paste a quote, or send a voice note, a photo, or a PDF. "
            "Use /compare after you have sent up to 3 quotes.",
        )
        return
    if text.strip().lower() in {"/new", "new quote"}:
        _clear_dialog(chat_id)
        send_telegram(chat_id, "Started a new quote. Paste the full text.")
        return
    business_id, quote_text = _split_business_prefix(text)
    dialog = _load_dialog(chat_id)
    if dialog and dialog.get("raw") and not _looks_like_new_quote(quote_text):
        quote_text = _merge_follow_up(dialog["raw"], quote_text)
    try:
        outcome = ingest_text(quote_text, business_id=business_id or bound, telegram_chat_id=chat_id)
    except LookupError as exc:
        send_telegram(chat_id, str(exc))
        return
    record = outcome["record"]
    held = _reject_absurd(record)
    decision = _decide_action(quote_text, record, held)
    record_id = f"tg-{message.get('message_id')}"
    if decision == "ask":
        _save_dialog(chat_id, quote_text)
        send_telegram(chat_id, _act(chat_id, outcome, decision, held, quote_text))
        return
    _clear_dialog(chat_id)
    sender = message.get("from") or {}
    _remember_compare(chat_id, record_id)
    send_telegram(chat_id, outcome["notice"], _quote_keyboard(record_id))
    from workers import submit

    submit(_finish_quote, chat_id, outcome, decision, held, quote_text, record, record_id, str(sender.get("id") or ""))


def _finish_quote(chat_id, outcome, decision, held, quote_text, record, record_id, telegram_user_id) -> None:
    """Save and email after Telegram already has the quote."""
    try:
        if record.get("company_id") != "unassigned" and (record.get("business") or {}).get("id") != "unassigned":
            _store_record(record, record_id, chat_id=chat_id, telegram_user_id=telegram_user_id)
        _act(chat_id, outcome, decision, held, quote_text)
    except Exception as exc:  # noqa: BLE001 — the chat already has the quote
        print(f"[intake] save skipped: {exc}")


def poll_telegram_once() -> int:
    from cache import get_text, set_text

    offset = 0
    saved = get_text("tg:offset")
    if saved and saved.strip().isdigit():
        offset = int(saved.strip())
    elif OFFSET_PATH.exists():
        offset = int(OFFSET_PATH.read_text().strip() or "0")
    body = telegram_api("getUpdates", {"timeout": 25, "offset": offset})
    handled = 0
    for update in body.get("result") or []:
        offset = int(update["update_id"]) + 1
        try:
            callback = update.get("callback_query")
            if callback:
                _handle_callback(callback)
                handled += 1
                continue
            message = update.get("message") or update.get("channel_post")
            if message and (
                message.get("text") or message.get("caption") or message.get("voice")
                or message.get("audio") or message.get("photo") or message.get("document")
            ):
                heavy = message.get("voice") or message.get("audio") or message.get("photo") or message.get("document")
                if heavy:
                    from workers import submit

                    submit(handle_telegram_message, message)
                else:
                    handle_telegram_message(message)
                handled += 1
        except Exception as exc:  # noqa: BLE001 — advance past a message that already failed once
            print(f"[intake] update skipped: {exc}")
        finally:
            set_text("tg:offset", str(offset))
    return handled


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


def _store_record(record: dict, name: str, *, chat_id: str | None = None, telegram_user_id: str | None = None) -> None:
    company_id = (record.get("business") or {}).get("id")
    if company_id:
        record["company_id"] = company_id
    folder = ROOT / "state" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        from supabase_sync import sync_quote

        sync_quote(record, name, chat_id=chat_id, telegram_user_id=telegram_user_id)
    except Exception as exc:  # noqa: BLE001 — a local quote still stands if Supabase is down
        print(f"[intake] Supabase sync skipped: {exc}")


_LOCK_HANDLE = None


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
    print("Quote intake running. Telegram and email poll every cycle.")
    last_mail = 0.0
    while True:
        try:
            if os.environ.get("TELEGRAM_BOT_TOKEN"):
                poll_telegram_once()
            else:
                time.sleep(5)
            if time.time() - last_mail > 60:
                poll_email_once()
                last_mail = time.time()
        except Exception as exc:  # noqa: BLE001 — keep the intake loop alive
            message = str(exc)
            if "409" in message or "Conflict" in message:
                try:
                    telegram_api("deleteWebhook", {"drop_pending_updates": "false"})
                except Exception:
                    pass
                print("[intake] Telegram conflict. A second poller or a webhook was cleared. Retrying.")
            else:
                print(f"[intake] {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
