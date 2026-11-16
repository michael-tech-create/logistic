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
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

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
    open_session,
    port_risk_level,
    public_user,
    register,
    save_batch,
    save_payout_plan,
    set_port_risk,
    company_parallel,
    set_company_parallel,
    user_by_api_key,
    user_by_token,
)
from customs import to_customs_record
from market import enrich, load_fx_settings, save_fx_settings
from quote_agent import parse_freight_quote, parse_quote_smart

from bounty_bridge import router as bounty_router

app = FastAPI(title="Global customs quote API", version="1.0.0")
app.include_router(bounty_router)
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


class ForgotPasswordBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordBody(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class ParseBody(BaseModel):
    text: str


class ScrapeBody(BaseModel):
    terminal: str
    container: str
    chat_id: str | None = None
    whatsapp_to: str | None = None


class CompareBody(BaseModel):
    record_ids: list[str]
    agreed_freight_ngn: float | None = None
    equipment: str = "40ft"
    mode: str = "ocean"


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
    company = ensure_company(user)
    return {
        "id": company["code"],
        "legal_name": company["legal_name"],
        "home_country": company.get("home_country") or user.get("home_country") or "Nigeria",
        "default_currency": "USD",
        "default_incoterms": None,
        "notify_email": company.get("notify_email") or user.get("email"),
        "parallel_usd_ngn": company.get("custom_parallel_ngn"),
        "port_risk_level": company.get("port_risk_level") or "normal",
    }


def enforce_plan_quota(user: dict, count: int = 1) -> None:
    """Reject the request before a parse when the account is over its monthly cap."""
    from api.store import connect, using_cloud

    if using_cloud():
        row = user
    else:
        with connect() as conn:
            row = conn.execute(
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
    started = time.perf_counter()
    enforce_plan_quota(user, 1)
    quote = parse_quote_smart(text)
    business = _business(user)
    record = enrich(to_customs_record(quote, business), business)
    if not record.get("line_items"):
        raise HTTPException(400, "No priced charges were found. Add amounts and currencies to the quote.")
    try:
        consume(user["id"], 1)
    except PermissionError as exc:
        raise HTTPException(402, str(exc)) from exc
    from duty import estimate_duty
    from shipment_costs import source_hints
    record["duty_estimate"] = estimate_duty(text, record)
    record["shipment_hints"] = source_hints(text)
    record["processing"] = {"milliseconds": round((time.perf_counter() - started) * 1000), "scope": "quote preparation; excludes queue, delivery, export, and human review"}
    return record


@app.get("/health")
def health():
    from api.store import using_cloud
    redis_ok = False
    try:
        from cache import redis_client

        client = redis_client()
        redis_ok = bool(client and client.ping())
    except Exception:
        redis_ok = False
    return {
        "ok": True,
        "store": "supabase" if using_cloud() else "sqlite",
        "durable": using_cloud(),
        "redis": redis_ok,
    }


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
    user = current_user(authorization, x_api_key)
    settings = load_fx_settings()
    parallel = company_parallel(ensure_company(user)["code"])
    if parallel is not None:
        settings["parallel_usd_ngn"] = parallel
    return settings


@app.post("/v1/rates")
def set_rates(body: RateBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    updates = body.model_dump(exclude_none=True)
    if "parallel_usd_ngn" in updates:
        set_company_parallel(ensure_company(user)["code"], updates.pop("parallel_usd_ngn"))
    saved = save_fx_settings(updates) if updates else load_fx_settings()
    parallel = company_parallel(ensure_company(user)["code"])
    if parallel is not None:
        saved["parallel_usd_ngn"] = parallel
    return saved


@app.get("/v1/company")
def company(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    row = ensure_company(user)
    return {
        "code": row["code"],
        "legal_name": row["legal_name"],
        "port_risk": port_risk_level(row["code"]),
        "link_command": f"/link {row['code']}",
    }


@app.post("/v1/port-risk")
def update_port_risk(body: PortRiskBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    try:
        return set_port_risk(body.level, ensure_company(user)["code"])
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


def _company_id(record: dict) -> str | None:
    return record.get("company_id") or (record.get("business") or {}).get("id")


def _owned_quote(user: dict, record_id: str) -> dict:
    from api.store import using_cloud
    from desk_ops import load_record
    from supabase_sync import get_quote

    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id):
        raise HTTPException(404, "Quote not found.")
    company_id = ensure_company(user)["code"]
    record = get_quote(record_id, company_id) if using_cloud() else load_record(record_id)
    if record is None or _company_id(record) != company_id:
        raise HTTPException(404, "Quote not found.")
    return {**record, "record_id": record_id}


def _save_desk_quote(record: dict, user: dict, *, source_text: str | None = None) -> dict:
    from desk_ops import save_record

    record.setdefault("record_id", "desk-" + secrets.token_hex(12))
    record["company_id"] = ensure_company(user)["code"]
    if source_text is not None:
        record["source_text"] = source_text
    save_record(record["record_id"], record)
    if record.get("sync_error"):
        raise HTTPException(503, "The quote could not be synced. Please try again when storage is available.")
    from bounty_bridge import enqueue
    enqueue(record)
    return record


@app.get("/v1/inbox")
def inbox(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    """Quotes for the signed-in company only, newest first."""
    user = current_user(authorization, x_api_key)
    company_id = ensure_company(user)["code"]
    from supabase_sync import list_quotes

    remote = list_quotes(company_id)
    if remote is not None:
        return {"records": remote}
    folder = ROOT / "state" / "records"
    records = []
    if folder.exists():
        files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files:
            record = json.loads(path.read_text(encoding="utf-8"))
            if _company_id(record) != company_id:
                continue
            record["record_id"] = path.stem
            records.append(record)
            if len(records) >= 20:
                break
    return {"records": records}


@app.delete("/v1/inbox/{record_id}")
def delete_inbox_record(record_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    company_id = ensure_company(user)["code"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id):
        raise HTTPException(400, "Unknown quote id.")
    from supabase_sync import delete_quote

    removed = delete_quote(record_id, company_id)
    path = ROOT / "state" / "records" / f"{record_id}.json"
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
        if _company_id(record) != company_id:
            raise HTTPException(404, "Quote not found.")
        path.unlink()
        removed = True
    if not removed:
        raise HTTPException(404, "Quote not found.")
    return {"deleted": record_id}


@app.post("/v1/auth/register")
def auth_register(body: RegisterBody):
    try:
        user = register(body.email, body.password, body.business_name, body.home_country)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return open_session(user)


@app.post("/v1/auth/login")
def auth_login(body: LoginBody):
    try:
        return login(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/v1/me")
def me(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    return public_user(current_user(authorization, x_api_key))


@app.post("/v1/auth/forgot-password")
def auth_forgot_password(body: ForgotPasswordBody, background_tasks: BackgroundTasks):
    from api.password_reset import RESET_MESSAGE, ensure_email_ready, send_reset_link

    email = body.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(400, "Enter a valid email address.")
    try:
        page_url = ensure_email_ready()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    background_tasks.add_task(send_reset_link, email, page_url)
    return {"message": RESET_MESSAGE}


@app.post("/v1/auth/reset-password")
def auth_reset_password(body: ResetPasswordBody):
    from api.password_reset import reset_password

    try:
        reset_password(body.token, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"message": "Your password has been reset. Sign in with your new password."}


class ExtractBody(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    idempotency_key: str = Field(min_length=1, max_length=128)


@app.post("/api/v1/extract")
def extract_for_bounty(body: ExtractBody, x_api_key: str | None = Header(default=None)):
    """Internal extract for the bounty agent. Does not use a customer API key or quota."""
    from bounty_bridge import authorize, extract
    authorize(x_api_key)
    if not body.text.strip():
        raise HTTPException(400, "Quote text is empty.")
    return extract(body.text, body.idempotency_key, parse_freight_quote)


@app.post("/v1/quotes/parse")
def parse_quote(body: ParseBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    if not body.text.strip():
        raise HTTPException(400, "Quote text is empty.")
    return _save_desk_quote(_parse_for_user(user, body.text), user, source_text=body.text)


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
    sources = []
    from media_intake import read_document
    for upload in files:
        raw = await upload.read(10 * 1024 * 1024 + 1)
        name = (upload.filename or "quote").lower()
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(400, f"{upload.filename}: the maximum file size is 10 MB.")
        started = time.perf_counter()
        try:
            text = await run_in_threadpool(read_document, raw, name, upload.content_type or "")
        except ValueError as exc:
            raise HTTPException(400, f"{upload.filename}: {exc}") from exc
        except Exception as exc:
            raise HTTPException(503, "The document reader is unavailable. Try again or paste the quote text. No parse was charged for this file.") from exc
        sources.append((upload.filename, text, round((time.perf_counter() - started) * 1000)))
    records = []
    for filename, text, reading_ms in sources:
        record = await run_in_threadpool(_parse_for_user, user, text)
        record["source_file"] = filename
        record["source_channel"] = "upload"
        record["processing"]["milliseconds"] += reading_ms
        record["processing"]["scope"] = "attachment reading and quote preparation; excludes queue, delivery, export, and human review"
        await run_in_threadpool(_save_desk_quote, record, user, source_text=text)
        records.append(record)
    batch_id = secrets.token_urlsafe(12)
    await run_in_threadpool(save_batch, user["id"], batch_id, json.dumps(records))
    return {"batch_id": batch_id, "count": len(records), "records": records}


def _batch(authorization: str | None, x_api_key: str | None, batch_id: str) -> tuple[dict, list]:
    user = current_user(authorization, x_api_key)
    records = load_batch(user["id"], batch_id)
    if records is None:
        raise HTTPException(404, "Batch not found.")
    records = [_owned_quote(user, record["record_id"]) if record.get("record_id") else record for record in records]
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


@app.get("/v1/quotes/batch/{batch_id}")
def batch_details(batch_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    _, records = _batch(authorization, x_api_key, batch_id)
    return {"batch_id": batch_id, "records": records}


@app.post("/v1/quotes/{record_id}/review")
def review_quote(record_id: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    record = _owned_quote(user, record_id)
    movement = record.get("movement") or {}
    commercial = record.get("commercial") or {}
    missing = []
    for field in ("origin", "destination"):
        if not (movement.get(field) or {}).get("location_name"):
            missing.append(field)
    if not record.get("line_items") or not commercial.get("currency") or float(commercial.get("total_amount") or 0) <= 0:
        missing.append("priced charges")
    if missing:
        raise HTTPException(400, "Add " + ", ".join(missing) + " before marking this quote checked. Correct the source and parse it again.")
    record["desk_review"] = {"status": "reviewed", "reviewed_at": datetime.now(timezone.utc).isoformat(), "reviewed_by": user["email"]}
    return _save_desk_quote(record, user)


@app.get("/v1/quotes/{record_id}/export/{kind}")
def export_quote(record_id: str, kind: str, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    record = _owned_quote(user, record_id)
    if kind == "pdf":
        data, media = build_pdf([record], user["business_name"]), "application/pdf"
    elif kind == "xlsx":
        data, media = build_xlsx([record], user["business_name"]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise HTTPException(400, "Choose pdf or xlsx.")
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{record_id}.{kind}"'})


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
    user = current_user(authorization, x_api_key)
    return {"reviews": list_reviews(ensure_company(user)["code"])}


@app.post("/v1/reviews/{review_id}")
def review_decision(review_id: int, body: ReviewBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    if body.status not in {"approved", "rejected"}:
        raise HTTPException(400, "Status must be approved or rejected.")
    from api.store import get_review

    company_id = ensure_company(current_user(authorization, x_api_key))["code"]
    current = get_review(review_id, company_id)
    if current is None:
        raise HTTPException(404, "Review not found.")
    if current.get("status") != "pending":
        raise HTTPException(409, "This review has already been handled. Refresh the approvals list.")
    if body.status == "approved" and current.get("kind") in {"pay", "clear"}:
        return _submit_review(current, company_id, "pending")
    try:
        row = resolve_review(review_id, body.status, None, company_id, expected_status="pending")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(409, "This review has already been handled. Refresh the approvals list.")
    return row


def _submit_review(current: dict, company_id: str, expected_status: str):
    from actions import execute_approved

    claimed = resolve_review(current["id"], "processing", "Approved. Submission started; check with the provider if no outcome appears. Do not submit again.", company_id, expected_status=expected_status)
    if claimed is None:
        raise HTTPException(409, "This request has already been handled. Refresh the approvals list.")
    result = execute_approved(claimed)
    status = "executed" if result["done"] else result.get("status", "execution_uncertain")
    row = resolve_review(current["id"], status, result["note"], company_id, expected_status="processing")
    if row is None:
        raise HTTPException(409, "Submission status changed. Refresh the approvals list and check with the provider.")
    return {**row, "execution": result}


@app.post("/v1/reviews/{review_id}/execute")
def review_execute(review_id: int, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from api.store import get_review

    company_id = ensure_company(current_user(authorization, x_api_key))["code"]
    current = get_review(review_id, company_id)
    if current is None:
        raise HTTPException(404, "Review not found.")
    if current.get("status") != "approved" or current.get("kind") not in {"pay", "clear"}:
        raise HTTPException(409, "Only an approved request that has not been submitted can be sent. Refresh the approvals list.")
    return _submit_review(current, company_id, "approved")


@app.post("/v1/whatsapp/send")
def whatsapp_send(body: dict, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    from desk_ops import WhatsAppSend, send_whatsapp

    try:
        payload = WhatsAppSend.model_validate(body)
        return send_whatsapp(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/quotes/{record_id}/resolve-flag")
def resolve_quote_flag(
    record_id: str,
    body: dict,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    user = current_user(authorization, x_api_key)
    from desk_ops import FlagResolution, resolve_flag

    record = _owned_quote(user, record_id)
    try:
        action = FlagResolution.model_validate(body)
        result = resolve_flag(record, action.flag_id, action.option, action.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _save_desk_quote(record, user)
    pdf = None
    if result["recalculated"]:
        import base64

        pdf = base64.b64encode(build_pdf([record], user["business_name"])).decode()
    return {**result, "record_id": record_id, "record": record, "pdf_base64": pdf, "total_amount": (record.get("commercial") or {}).get("total_amount")}


@app.post("/v1/terminal/scrape")
def terminal_scrape(body: ScrapeBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    from desk_ops import WhatsAppSend, send_whatsapp
    from terminal_scrape import needs_free_time_alert, scrape_container

    try:
        status = scrape_container(body.terminal, body.container)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    alerted = False
    if needs_free_time_alert(status):
        text = (
            f"Free time alert: {status.container} at {status.terminal} has "
            f"{status.free_hours_remaining} hours left. Vessel {status.vessel_name or 'n/a'}. "
            f"Yard {status.yard_location or 'n/a'}. Demurrage NGN {status.demurrage_liability_ngn:,.0f}."
        )
        _alert_telegram(text, body.chat_id)
        if body.whatsapp_to:
            send_whatsapp(WhatsAppSend(to=body.whatsapp_to, body=text, priority="high"))
        alerted = True
    return {**status.model_dump(), "alerted": alerted}


@app.post("/v1/quotes/compare")
def compare_quotes(body: CompareBody, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user = current_user(authorization, x_api_key)
    from desk_ops import comparison_matrix, load_record, matrix_files, save_market_rate

    company = ensure_company(user)["code"]
    if not 1 <= len(body.record_ids) <= 3:
        raise HTTPException(400, "Send 1 to 3 quote ids.")
    records = []
    for record_id in body.record_ids:
        record = load_record(record_id)
        owner = (record or {}).get("company_id")
        if record is None or (owner and owner != company):
            raise HTTPException(404, f"Quote {record_id} not found.")
        records.append(record)
    try:
        matrix = comparison_matrix(records)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    benchmark = None
    if body.agreed_freight_ngn:
        benchmark = save_market_rate(matrix["lane"], body.agreed_freight_ngn, body.equipment, body.mode)
    xlsx, pdf = matrix_files(matrix, user["business_name"])
    import base64

    return {
        "matrix": matrix,
        "benchmark": benchmark,
        "xlsx_base64": base64.b64encode(xlsx).decode(),
        "pdf_base64": base64.b64encode(pdf).decode(),
    }


@app.get("/v1/market-rates")
def market_rates(lane: str, equipment: str = "40ft", authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    current_user(authorization, x_api_key)
    from desk_ops import lane_benchmark

    return lane_benchmark(lane, equipment)


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
    from telegram_jobs import schedule_pending
    schedule_pending()


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """Acknowledge Telegram immediately. Transcription and PDF reading run after the 200."""
    if os.environ.get("TELEGRAM_DELIVERY_MODE", "polling").lower() != "webhook":
        raise HTTPException(409, "Webhook intake is disabled. Set TELEGRAM_DELIVERY_MODE=webhook to use it.")
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        raise HTTPException(503, "Configure TELEGRAM_WEBHOOK_SECRET before enabling webhook intake.")
    if not secrets.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", "").encode(), expected.encode()):
        raise HTTPException(401, "Invalid Telegram secret.")
    from telegram_jobs import enqueue
    try:
        update = await request.json()
        enqueue(update)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(400, "Invalid Telegram update.") from exc
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

# Imported after core helpers so channel workers can reuse ownership checks.
from api.operations import router as operations_router
app.include_router(operations_router)
