"""Agency accounts in Supabase. Used when SUPABASE_URL and the service role key are set."""

from __future__ import annotations

import json
import secrets
import time
import urllib.error

from api.store import (
    PLAN_CODE,
    PLANS,
    PORT_BUFFERS,
    TRIAL_PARSES,
    _check_password,
    _hash_password,
    public_user,
)
from supabase_sync import _request


def _one(path: str) -> dict | None:
    rows = _request("GET", path, None)
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def _patch(path: str, payload: dict) -> dict | None:
    rows = _request("PATCH", path, payload)
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def _insert(table: str, payload: dict) -> dict:
    try:
        saved = _request("POST", table, payload)
    except urllib.error.HTTPError as exc:
        if exc.code in {409, 400}:
            body = exc.read().decode()
            if "email" in body or "users_email" in body or "duplicate" in body.lower():
                raise ValueError("An account with that email already exists.") from exc
        raise
    if isinstance(saved, list) and saved:
        return saved[0]
    raise RuntimeError(f"Supabase did not return a {table} row.")


def register(email: str, password: str, business_name: str, home_country: str = "Nigeria") -> dict:
    email = email.lower().strip()
    now = int(time.time())
    user = _insert("users", {
        "email": email,
        "password_hash": _hash_password(password),
        "business_name": business_name.strip(),
        "home_country": home_country,
        "api_key": "qk_" + secrets.token_urlsafe(24),
        "quota_remaining": TRIAL_PARSES,
        "period_end": None,
        "created_at": now,
        "plan_code": "trial",
        "plan_parses": TRIAL_PARSES,
    })
    code = "co-" + secrets.token_hex(3)
    _insert("companies", {
        "user_id": user["id"],
        "code": code,
        "legal_name": business_name.strip(),
        "home_country": home_country,
        "notify_email": email,
        "telegram_chat_ids": [],
        "inbound_emails": [],
        "port_risk_level": "normal",
    })
    updated = _patch(f"users?id=eq.{user['id']}", {"company_code": code})
    return updated or {**user, "company_code": code}


def login(email: str, password: str) -> dict:
    user = _one(f"users?email=eq.{urllib_quote(email.lower().strip())}&select=*")
    if user is None or not _check_password(password, user["password_hash"]):
        raise ValueError("Email or password is wrong.")
    return open_session(user)


def open_session(user: dict) -> dict:
    token = secrets.token_urlsafe(32)
    _insert("sessions", {"token": token, "user_id": user["id"], "created_at": int(time.time())})
    public = public_user(user)
    public["token"] = token
    return public


def issue_password_reset(email: str, token_hash: str, expires_at: int, now: int) -> bool:
    path = (f"users?email=eq.{urllib_quote(email.lower().strip())}"
            f"&or=(reset_requested_at.is.null,reset_requested_at.lte.{now - 60})&select=id")
    return _patch(path, {"reset_token_hash": token_hash, "reset_expires_at": expires_at, "reset_requested_at": now}) is not None


def ensure_password_reset_ready() -> None:
    try:
        _request("GET", "users?select=reset_token_hash,reset_expires_at,reset_requested_at&limit=0", None)
    except Exception as exc:
        raise RuntimeError("Password recovery is not available yet. Please contact your workspace administrator.") from exc


def complete_password_reset(token_hash: str, password_hash: str, now: int) -> bool:
    # A database function keeps token consumption, password update, and session
    # revocation atomic even when multiple API processes receive the same link.
    return _request("POST", "rpc/complete_password_reset", {"p_token_hash": token_hash, "p_password_hash": password_hash}) is True


def user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    session = _one(f"sessions?token=eq.{urllib_quote(token)}&select=user_id")
    if session is None:
        return None
    return _one(f"users?id=eq.{session['user_id']}&select=*")


def user_by_api_key(api_key: str | None) -> dict | None:
    if not api_key:
        return None
    return _one(f"users?api_key=eq.{urllib_quote(api_key)}&select=*")


def user_by_company(code: str) -> dict | None:
    company = _one(f"companies?code=eq.{urllib_quote(code)}&select=user_id")
    return _one(f"users?id=eq.{company['user_id']}&select=*") if company else None


def consume(user_id: int, count: int = 1) -> dict:
    row = _one(f"users?id=eq.{user_id}&select=*")
    if row is None:
        raise ValueError("Account not found.")
    if row["quota_remaining"] < count:
        raise PermissionError(
            f"Parse quota exceeded ({row['quota_remaining']} left, {count} required). "
            "The ₦15,000 plan allows 200 parses a month and the ₦50,000 plan allows 1,000."
        )
    updated = _patch(f"users?id=eq.{user_id}", {"quota_remaining": row["quota_remaining"] - count})
    return updated or row


def grant_plan(email: str, reference: str | None = None, plan_code: str = PLAN_CODE) -> dict | None:
    plan = PLANS.get(plan_code)
    if plan is None:
        raise ValueError(f"Unknown plan {plan_code}.")
    email = email.lower().strip()
    if reference and _one(f"payments?reference=eq.{urllib_quote(reference)}&select=reference"):
        return _one(f"users?email=eq.{urllib_quote(email)}&select=*")
    period_end = int(time.time()) + 30 * 24 * 3600
    updated = _patch(
        f"users?email=eq.{urllib_quote(email)}",
        {
            "quota_remaining": plan["parses"],
            "period_end": period_end,
            "plan_code": plan_code,
            "plan_parses": plan["parses"],
        },
    )
    if reference:
        _insert("payments", {"reference": reference, "email": email, "created_at": int(time.time())})
    return updated


def save_batch(user_id: int, batch_id: str, payload: str) -> None:
    _insert("batches", {
        "id": batch_id,
        "user_id": user_id,
        "payload": json.loads(payload),
        "created_at": int(time.time()),
    })


def load_batch(user_id: int, batch_id: str) -> dict | None:
    row = _one(f"batches?id=eq.{urllib_quote(batch_id)}&user_id=eq.{user_id}&select=payload")
    if row is None:
        return None
    payload = row["payload"]
    return json.loads(payload) if isinstance(payload, str) else payload


def ensure_company(user: dict) -> dict:
    row = _one(f"companies?user_id=eq.{user['id']}&select=*")
    if row:
        return row
    code = user.get("company_code") or ("co-" + secrets.token_hex(3))
    created = _insert("companies", {
        "user_id": user["id"],
        "code": code,
        "legal_name": user["business_name"],
        "home_country": user.get("home_country") or "Nigeria",
        "notify_email": user.get("email"),
        "telegram_chat_ids": [],
        "inbound_emails": [],
        "port_risk_level": "normal",
    })
    _patch(f"users?id=eq.{user['id']}", {"company_code": code})
    return created


def link_telegram(code: str, chat_id: str) -> dict | None:
    row = _one(f"companies?code=eq.{urllib_quote(code.strip())}&select=*")
    if row is None:
        return None
    for other in company_businesses():
        if other["id"] != code.strip() and str(chat_id) in other["telegram_chat_ids"]:
            raise ValueError("This chat is already linked to another company. Use /unlink before changing companies.")
    chats = _list(row.get("telegram_chat_ids"))
    if str(chat_id) not in chats:
        chats.append(str(chat_id))
    updated = _patch(f"companies?id=eq.{row['id']}", {"telegram_chat_ids": chats})
    if updated is None:
        raise ValueError("The company link could not be saved. Try /link again.")
    updated["telegram_chat_ids"] = chats
    return updated


def unlink_telegram(chat_id: str) -> None:
    rows = _request("GET", "companies?select=id,telegram_chat_ids", None)
    for row in rows if isinstance(rows, list) else []:
        chats = _list(row.get("telegram_chat_ids"))
        if str(chat_id) in chats:
            _patch(f"companies?id=eq.{row['id']}", {"telegram_chat_ids": [item for item in chats if item != str(chat_id)]})


def company_businesses() -> list[dict]:
    rows = _request("GET", "companies?select=*", None)
    businesses = []
    for row in rows if isinstance(rows, list) else []:
        businesses.append(_business(row))
    return businesses


def port_risk_level(company_code: str | None = None) -> str:
    if not company_code:
        return "normal"
    row = _one(f"companies?code=eq.{urllib_quote(company_code)}&select=port_risk_level")
    if row and row.get("port_risk_level"):
        return row["port_risk_level"]
    return "normal"


def set_port_risk(level: str, company_code: str | None = None) -> dict:
    if level not in PORT_BUFFERS:
        raise ValueError("Level must be normal, elevated, or severe.")
    if not company_code:
        return {"level": level, "buffer_ngn": PORT_BUFFERS[level]}
    updated = _patch(f"companies?code=eq.{urllib_quote(company_code)}", {"port_risk_level": level})
    if updated is None:
        raise ValueError("Company not found.")
    return {"level": level, "buffer_ngn": PORT_BUFFERS[level], "company_id": company_code}


def set_company_parallel(company_code: str, rate: float | None) -> None:
    _patch(f"companies?code=eq.{urllib_quote(company_code)}", {"custom_parallel_ngn": rate})


def company_parallel(company_code: str | None) -> float | None:
    if not company_code:
        return None
    row = _one(f"companies?code=eq.{urllib_quote(company_code)}&select=custom_parallel_ngn")
    if row is None or row.get("custom_parallel_ngn") is None:
        return None
    return float(row["custom_parallel_ngn"])


def queue_human_review(kind: str, summary: str, chat_id: str | None = None, detail: str = "", payload: dict | None = None, company_id: str | None = None) -> dict:
    row = _insert("human_reviews", {
        "kind": kind,
        "summary": summary,
        "detail": detail,
        "chat_id": chat_id,
        "status": "pending",
        "created_at": int(time.time()),
        "payload": payload,
        "company_id": company_id,
    })
    return {"id": row["id"], "kind": kind, "status": "pending", "summary": summary}


def list_reviews(company_id: str | None = None) -> list[dict]:
    path = "human_reviews?select=*&order=id.desc&limit=30"
    if company_id:
        path += f"&or=(company_id.eq.{urllib_quote(company_id)},company_id.is.null)"
    rows = _request("GET", path, None)
    return rows if isinstance(rows, list) else []


def get_review(review_id: int, company_id: str | None = None) -> dict | None:
    path = f"human_reviews?id=eq.{review_id}&select=*"
    if company_id:
        path += f"&or=(company_id.eq.{urllib_quote(company_id)},company_id.is.null)"
    return _one(path)


def resolve_review(review_id: int, status: str, execution_note: str | None = None, company_id: str | None = None, expected_status: str | None = None) -> dict | None:
    if status not in {"approved", "rejected", "executed", "pending", "processing", "execution_uncertain"}:
        raise ValueError("Invalid review status.")
    path = f"human_reviews?id=eq.{review_id}"
    if company_id:
        path += f"&company_id=eq.{urllib_quote(company_id)}"
    if expected_status:
        path += f"&status=eq.{urllib_quote(expected_status)}"
    return _patch(path, {"status": status, "execution_note": execution_note})


def _list(value) -> list:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    return [str(item) for item in json.loads(value)]


def _business(row: dict) -> dict:
    return {
        "id": row["code"],
        "legal_name": row["legal_name"],
        "home_country": row["home_country"],
        "telegram_chat_ids": _list(row.get("telegram_chat_ids")),
        "inbound_emails": _list(row.get("inbound_emails")),
        "notify_email": row.get("notify_email"),
        "port_risk_level": row.get("port_risk_level") or "normal",
        "parallel_usd_ngn": row.get("custom_parallel_ngn"),
        "default_currency": "USD",
        "default_incoterms": None,
    }


def urllib_quote(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")
