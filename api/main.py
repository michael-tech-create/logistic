"""Quote API for developers and the clearing-agent dashboard.

Auth: Authorization: Bearer <session> or X-API-Key.
Plan: ₦50,000 / 1,000 parses via Paystack. New accounts get 5 trial parses.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from api.billing import apply_event, initialize_checkout, verify_signature, verify_transaction
from api.exports import build_pdf, build_xlsx, pdf_to_text
from api.store import (
    apply_finance,
    list_reviews,
    resolve_review,
    consume,
    ensure_company,
    escrow_action,
    grant_plan,
    load_batch,
    login,
    port_risk_level,
    public_user,
    register,
    save_batch,
    save_payout_plan,
    set_port_risk,
    user_by_api_key,
    user_by_token,
)
from customs import to_customs_record
from market import enrich, load_fx_settings, save_fx_settings
from quote_agent import parse_quote_smart

app = FastAPI(title="Global customs quote API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterBody(BaseModel):
    email: str
    password: str
    business_name: str
    home_country: str = "Nigeria"


class LoginBody(BaseModel):
    email: str
    password: str


class ParseBody(BaseModel):
    text: str


class TerminalStatus(BaseModel):
    container: str = ""
    gate_out: str = ""
    vessel: str = ""
    berth: str = ""
    free_days_left: int = 0
    chat_id: str | None = None
    feed_down: bool = False
    source: str = ""


class CheckoutBody(BaseModel):
    callback_url: str | None = None
    plan: str = "quote-1000"


class VerifyBody(BaseModel):
    reference: str


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def current_user(authorization: str | None, x_api_key: str | None):
    user = user_by_token(_bearer(authorization)) or user_by_api_key(x_api_key)
    if user is None:
        raise HTTPException(401, "Sign in or send X-API-Key.")
    return user


def _business(user: dict) -> dict:
    return {
        "id": f"user-{user['id']}",
        "legal_name": user["business_name"],
        "home_country": user.get("home_country") or "Nigeria",
        "default_currency": "USD",
        "default_incoterms": None,
    }


def enforce_plan_quota(user: dict, count: int = 1) -> None:
    """Reject the request before a parse when the account is over its monthly cap."""
    from api.store import connect

    row = connect().execute(
        "SELECT quota_remaining, plan_code, plan_parses FROM users WHERE id = ?",
        (user["id"],),
    ).fetchone()
    remaining = int(row["quota_remaining"] or 0) if row else 0
    cap = int(row["plan_parses"] or 0) if row else 0
    if remaining < count:
        raise HTTPException(
            402,
            f"Parse quota exceeded ({remaining} left, cap {cap or 'trial'}). "
            "The ₦15,000 plan allows 200 parses a month and the ₦50,000 plan allows 1,000.",
        )


def _parse_for_user(user: dict, text: str) -> dict:
    enforce_plan_quota(user, 1)
    try:
        consume(user["id"], 1)
    except PermissionError as exc:
        raise HTTPException(402, str(exc)) from exc
    quote = parse_quote_smart(text)
    return enrich(to_customs_record(quote, _business(user)), _business(user))


@app.get("/health")
def health():
    return {"ok": True}


class RateBody(BaseModel):
    cbn_usd_ngn: float | None = None
    parallel_usd_ngn: float | None = None
    finance_fee_rate: float | None = None
    demurrage_buffer_ngn: float | None = None
    fallback_official_usd_ngn: float | None = None
    fallback_parallel_usd_ngn: float | None = None


class PortRiskBody(BaseModel):
    level: str


class FinanceBody(BaseModel):
    record_id: str
    principal_ngn: float


class EscrowBody(BaseModel):
    record_id: str
    amount_ngn: float
    action: str


class PayoutBody(BaseModel):
    record_id: str
    trucker_account: str = ""
    agent_account: str = ""
    customs_account: str = ""


@app.get("/v1/rates")
def rates(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    return load_fx_settings()


@app.post("/v1/rates")
def set_rates(body: RateBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    return save_fx_settings(body.model_dump(exclude_none=True))


@app.get("/v1/company")
def company(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    row = ensure_company(user)
    return {"code": row["code"], "legal_name": row["legal_name"], "port_risk": port_risk_level(), "link_command": f"/link {row['code']}"}


@app.post("/v1/port-risk")
def update_port_risk(body: PortRiskBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    try:
        return set_port_risk(body.level)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/finance/apply")
def finance_apply(body: FinanceBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    if body.principal_ngn <= 0:
        raise HTTPException(400, "There is no duty amount to finance.")
    return apply_finance(user["id"], body.record_id, body.principal_ngn)


@app.post("/v1/escrow")
def escrow(body: EscrowBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    try:
        return escrow_action(user["id"], body.record_id, body.amount_ngn, body.action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/payouts")
def payouts(body: PayoutBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    return save_payout_plan(user["id"], body.record_id, body.trucker_account, body.agent_account, body.customs_account)


@app.get("/v1/channels/email")
def email_channel(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    import imaplib
    host, user_name, password = os.environ.get("IMAP_HOST"), os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    if not (host and user_name and password):
        return {"ok": False, "detail": "IMAP is not configured."}
    try:
        client = imaplib.IMAP4_SSL(host, int(os.environ.get("IMAP_PORT", "993")))
        client.login(user_name, password)
        client.logout()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)[:180]}
    return {"ok": True, "detail": "Gmail inbox login succeeded."}


@app.get("/v1/inbox")
def inbox(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    """Quotes that Telegram or email already parsed, newest first."""
    current_user(authorization, x_api_key)
    folder = ROOT / "state" / "records"
    records = []
    if folder.exists():
        files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:20]
        for path in files:
            record = json.loads(path.read_text(encoding="utf-8"))
            record["record_id"] = path.stem
            records.append(record)
    return {"records": records}


@app.delete("/v1/inbox/{record_id}")
def delete_inbox_record(record_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id):
        raise HTTPException(400, "Unknown quote id.")
    path = ROOT / "state" / "records" / f"{record_id}.json"
    if not path.is_file():
        raise HTTPException(404, "Quote not found.")
    path.unlink()
    return {"deleted": record_id}


@app.post("/v1/auth/register")
def auth_register(body: RegisterBody):
    try:
        user = register(body.email, body.password, body.business_name, body.home_country)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session = login(body.email, body.password)
    return session


@app.post("/v1/auth/login")
def auth_login(body: LoginBody):
    try:
        return login(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc


@app.get("/v1/me")
def me(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    return public_user(current_user(authorization, x_api_key))


@app.post("/v1/quotes/parse")
def parse_quote(body: ParseBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    if not body.text.strip():
        raise HTTPException(400, "Quote text is empty.")
    return _parse_for_user(user, body.text)


@app.post("/v1/quotes/batch")
async def parse_batch(
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    user = current_user(authorization, x_api_key)
    if not files:
        raise HTTPException(400, "Upload at least one .pdf or .txt quote.")
    enforce_plan_quota(user, len(files))
    records = []
    for upload in files:
        raw = await upload.read()
        name = (upload.filename or "quote").lower()
        if name.endswith(".pdf"):
            from workers import submit

            text = submit(pdf_to_text, raw).result()
        else:
            text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            raise HTTPException(400, f"No text found in {upload.filename}.")
        record = _parse_for_user(user, text)
        record["source_file"] = upload.filename
        records.append(record)
    batch_id = secrets.token_urlsafe(12)
    save_batch(user["id"], batch_id, json.dumps(records))
    return {"batch_id": batch_id, "count": len(records), "records": records}


def _batch(authorization: str | None, x_api_key: str | None, batch_id: str) -> tuple[dict, list]:
    user = current_user(authorization, x_api_key)
    records = load_batch(user["id"], batch_id)
    if records is None:
        raise HTTPException(404, "Batch not found.")
    return user, records


@app.get("/v1/quotes/batch/{batch_id}.xlsx")
def download_xlsx(batch_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user, records = _batch(authorization, x_api_key, batch_id)
    data = build_xlsx(records, user["business_name"])
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{user["business_name"]}-quotes.xlsx"'},
    )


@app.get("/v1/quotes/batch/{batch_id}.pdf")
def download_pdf(batch_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user, records = _batch(authorization, x_api_key, batch_id)
    data = build_pdf(records, user["business_name"])
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="quotes.pdf"'})


def _callback_url(requested: str | None) -> str:
    fallback = os.environ.get("PAYSTACK_CALLBACK_URL", "http://127.0.0.1:3000/billing")
    if not requested:
        return fallback
    parsed = urlparse(requested)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path.rstrip("/") != "/billing":
        raise HTTPException(400, "callback_url must be an absolute http(s) URL ending in /billing.")
    return requested


@app.post("/v1/billing/checkout")
def checkout(body: CheckoutBody | None = None, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    callback = _callback_url(body.callback_url if body else None)
    plan = (body.plan if body else None) or "quote-1000"
    from api.store import PLANS
    if plan not in PLANS:
        raise HTTPException(400, "Choose quote-200 (₦15,000 / 200 parses) or quote-1000 (₦50,000 / 1,000 parses).")
    try:
        data = initialize_checkout(user["email"], callback, plan)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "authorization_url": data.get("authorization_url"),
        "reference": data.get("reference"),
        "callback_url": callback,
        "amount_ngn": {"quote-200": 15000, "quote-1000": 50000}.get(plan, 50000),
        "plan": plan,
    }


@app.post("/v1/billing/verify")
def verify_payment(body: VerifyBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    try:
        result = verify_transaction(body.reference)
    except RuntimeError as exc:
        raise HTTPException(402, str(exc)) from exc
    if result["email"].lower() != user["email"].lower():
        raise HTTPException(403, "This payment belongs to a different account.")
    granted = grant_plan(user["email"], result["reference"], result.get("plan") or "quote-1000")
    return {
        "reference": result["reference"],
        "quota_remaining": None if granted is None else granted["quota_remaining"],
        "callback_url": os.environ.get("PAYSTACK_CALLBACK_URL", "http://127.0.0.1:3000/billing"),
    }


def _alert_telegram(text: str, chat_id: str | None) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    chats = [chat_id] if chat_id else []
    if not chats:
        path = ROOT / "businesses.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for business in data.get("businesses") or []:
                chats.extend(str(item) for item in business.get("telegram_chat_ids") or [])
    import urllib.request

    for chat in chats:
        body = json.dumps({"chat_id": chat, "text": text[:4000]}).encode()
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=20).read()


class ReviewBody(BaseModel):
    status: str


@app.get("/v1/reviews")
def reviews(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    return {"reviews": list_reviews()}


@app.post("/v1/reviews/{review_id}")
def review_decision(review_id: int, body: ReviewBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    try:
        row = resolve_review(review_id, body.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Review not found.")
    return row


@app.post("/v1/terminal/status")
def terminal_status(body: TerminalStatus, x_terminal_token: str | None = Header(default=None)):
    """Receive a terminal watch update. Alert Telegram when gate-out is still open inside 2 free days."""
    expected = os.environ.get("TERMINAL_WEBHOOK_SECRET")
    if expected and x_terminal_token != expected:
        raise HTTPException(401, "Invalid terminal token.")
    if body.feed_down:
        from api.store import queue_human_review

        review = queue_human_review("terminal", "Live port feed is down", body.chat_id, body.source or body.gate_out)
        _alert_telegram(
            f"The live port feed is down. Review {review['id']} is waiting for a person. {body.gate_out}",
            body.chat_id,
        )
        return {"container": body.container, "alerted": True, "review_id": review["id"], "feed_down": True}
    nearing = body.gate_out.lower() not in {"out", "gated out", "gated-out", "not yet arrived"} and body.free_days_left <= 2
    if nearing:
        _alert_telegram(
            f"Demurrage watch: container {body.container} is still {body.gate_out}. "
            f"{body.free_days_left} free day(s) left. Vessel {body.vessel or 'n/a'}, berth {body.berth or 'n/a'}.",
            body.chat_id,
        )
    return {"container": body.container, "alerted": nearing}


def _run_telegram_update(update: dict) -> None:
    from automate import handle_telegram_message, _handle_callback

    callback = update.get("callback_query")
    if callback:
        _handle_callback(callback)
        return
    message = update.get("message") or update.get("channel_post") or {}
    if message.get("text") or message.get("caption") or message.get("voice") or message.get("audio") or message.get("photo") or message.get("document"):
        handle_telegram_message(message)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """Acknowledge Telegram immediately. Transcription and PDF reading run after the 200."""
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if expected and request.headers.get("x-telegram-bot-api-secret-token") != expected:
        raise HTTPException(401, "Invalid Telegram secret.")
    update = await request.json()
    background.add_task(_run_telegram_update, update)
    return {"ok": True}


@app.post("/v1/billing/webhook")
async def webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not verify_signature(raw, signature):
        raise HTTPException(401, "Invalid Paystack signature.")
    event = json.loads(raw.decode())
    user = apply_event(event)
    return {"granted": bool(user)}


@app.post("/mcp")
async def mcp(request: Request, x_api_key: str | None = Header(default=None)):
    """Minimal MCP JSON-RPC for tool parse_freight_quote."""
    raw = await request.body()
    if not raw.strip():
        raise HTTPException(400, "POST /mcp needs a JSON-RPC body. In /docs, fill the request body before Execute. Example: {\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "MCP body must be JSON.") from exc
    method = body.get("method")
    rpc_id = body.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "quote-customs", "version": "1.0.0"}, "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{
            "name": "parse_freight_quote",
            "description": "Normalize a freight quote into the global customs record. Uses one parse from the API key quota.",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        }]}
    elif method == "tools/call":
        user = user_by_api_key(x_api_key)
        if user is None:
            raise HTTPException(401, "X-API-Key is required for tools/call.")
        params = body.get("params") or {}
        if params.get("name") != "parse_freight_quote":
            raise HTTPException(400, "Unknown tool.")
        text = ((params.get("arguments") or {}).get("text")) or ""
        record = _parse_for_user(user, text)
        result = {"content": [{"type": "text", "text": json.dumps(record)}]}
    else:
        result = {}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
