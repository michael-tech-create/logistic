"""SQLite accounts, API keys, and monthly parse quota."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("QUOTE_DB", ROOT / "state" / "billing.sqlite"))
TRIAL_PARSES = 5
PLANS = {
    "quote-200": {"parses": 200, "kobo": 1_500_000, "price_ngn": 15000},
    "quote-1000": {"parses": 1000, "kobo": 5_000_000, "price_ngn": 50000},
}
PLAN_CODE = "quote-1000"
PLAN_PARSES = PLANS[PLAN_CODE]["parses"]
PLAN_KOBO = PLANS[PLAN_CODE]["kobo"]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            business_name TEXT NOT NULL,
            home_country TEXT DEFAULT 'Nigeria',
            api_key TEXT UNIQUE NOT NULL,
            quota_remaining INTEGER NOT NULL,
            period_end INTEGER,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "plan_code" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN plan_code TEXT DEFAULT 'trial'")
    if "plan_parses" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN plan_parses INTEGER DEFAULT 5")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            reference TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL,
            legal_name TEXT NOT NULL,
            home_country TEXT,
            telegram_chat_ids TEXT DEFAULT '[]',
            inbound_emails TEXT DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS finance_requests (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            record_id TEXT,
            principal_ngn REAL NOT NULL,
            fee_ngn REAL NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS escrow_ledger (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            record_id TEXT,
            amount_ngn REAL NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payout_plans (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            record_id TEXT,
            trucker_account TEXT,
            agent_account TEXT,
            customs_account TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS port_risk (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            level TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    if "company_code" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN company_code TEXT")
    company_cols = [row[1] for row in conn.execute("PRAGMA table_info(companies)")]
    for column, kind in (
        ("port_risk_level", "TEXT DEFAULT 'normal'"),
        ("custom_parallel_ngn", "REAL"),
        ("notify_email", "TEXT"),
    ):
        if column not in company_cols:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {column} {kind}")
    conn.commit()
    return conn


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def _check_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    check = _hash_password(password, salt).split("$", 1)[1]
    return secrets.compare_digest(check, digest)


def using_cloud() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def _require_durable() -> None:
    if os.environ.get("RENDER") == "true" and not using_cloud():
        raise RuntimeError(
            "Supabase is not configured. Accounts and quotes would be wiped when Render restarts. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, then run supabase/schema.sql."
        )


def register(email: str, password: str, business_name: str, home_country: str = "Nigeria") -> dict:
    _require_durable()
    if using_cloud():
        from api.cloud_store import register as cloud_register
        return cloud_register(email, password, business_name, home_country)
    conn = connect()
    api_key = "qk_" + secrets.token_urlsafe(24)
    now = int(time.time())
    try:
        cur = conn.execute(
            """
            INSERT INTO users (email, password_hash, business_name, home_country, api_key, quota_remaining, period_end, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (email.lower().strip(), _hash_password(password), business_name.strip(), home_country, api_key, TRIAL_PARSES, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists.") from exc
    user_id = cur.lastrowid
    code = "co-" + secrets.token_hex(3)
    conn.execute(
        "INSERT INTO companies (user_id, code, legal_name, home_country, notify_email) VALUES (?, ?, ?, ?, ?)",
        (user_id, code, business_name.strip(), home_country, email.lower().strip()),
    )
    conn.execute("UPDATE users SET company_code = ? WHERE id = ?", (code, user_id))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(user)


def login(email: str, password: str) -> dict:
    _require_durable()
    if using_cloud():
        from api.cloud_store import login as cloud_login
        return cloud_login(email, password)
    conn = connect()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    if user is None or not _check_password(password, user["password_hash"]):
        raise ValueError("Email or password is wrong.")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], int(time.time())))
    conn.commit()
    public = public_user(dict(user))
    public["token"] = token
    return public


def user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    if using_cloud():
        from api.cloud_store import user_by_token as cloud_user_by_token
        return cloud_user_by_token(token)
    conn = connect()
    row = conn.execute(
        """
        SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
        """,
        (token,),
    ).fetchone()
    return dict(row) if row else None


def user_by_api_key(api_key: str | None) -> dict | None:
    if not api_key:
        return None
    if using_cloud():
        from api.cloud_store import user_by_api_key as cloud_user_by_api_key
        return cloud_user_by_api_key(api_key)
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
    return dict(row) if row else None


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "business_name": user["business_name"],
        "home_country": user["home_country"],
        "api_key": user["api_key"],
        "quota_remaining": user["quota_remaining"],
        "period_end": user["period_end"],
        "plan": user.get("plan_code") or "trial",
        "plan_price_ngn": PLANS.get(user.get("plan_code") or "", {}).get("price_ngn", 0),
        "plan_parses": user.get("plan_parses") or TRIAL_PARSES,
        "plans": [
            {"code": code, "parses": plan["parses"], "price_ngn": plan["price_ngn"]}
            for code, plan in PLANS.items()
        ],
        "company_code": user.get("company_code"),
    }


def consume(user_id: int, count: int = 1) -> dict:
    if using_cloud():
        from api.cloud_store import consume as cloud_consume
        return cloud_consume(user_id, count)
    conn = connect()
    row = conn.execute("SELECT quota_remaining FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("Account not found.")
    if row["quota_remaining"] < count:
        raise PermissionError(
            f"Parse quota exceeded ({row['quota_remaining']} left, {count} required). "
            "The ₦15,000 plan allows 200 parses a month and the ₦50,000 plan allows 1,000."
        )
    conn.execute(
        "UPDATE users SET quota_remaining = quota_remaining - ? WHERE id = ?",
        (count, user_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(updated)


def grant_plan(email: str, reference: str | None = None, plan_code: str = PLAN_CODE) -> dict | None:
    plan = PLANS.get(plan_code)
    if plan is None:
        raise ValueError(f"Unknown plan {plan_code}.")
    if using_cloud():
        from api.cloud_store import grant_plan as cloud_grant_plan
        return cloud_grant_plan(email, reference, plan_code)
    conn = connect()
    email = email.lower().strip()
    if reference:
        existing = conn.execute("SELECT reference FROM payments WHERE reference = ?", (reference,)).fetchone()
        if existing:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None
    period_end = int(time.time()) + 30 * 24 * 3600
    conn.execute(
        """
        UPDATE users
        SET quota_remaining = ?, period_end = ?, plan_code = ?, plan_parses = ?
        WHERE email = ?
        """,
        (plan["parses"], period_end, plan_code, plan["parses"], email),
    )
    if reference:
        conn.execute(
            "INSERT INTO payments (reference, email, created_at) VALUES (?, ?, ?)",
            (reference, email, int(time.time())),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def save_batch(user_id: int, batch_id: str, payload: str) -> None:
    if using_cloud():
        from api.cloud_store import save_batch as cloud_save_batch
        return cloud_save_batch(user_id, batch_id, payload)
    conn = connect()
    conn.execute(
        "INSERT INTO batches (id, user_id, payload, created_at) VALUES (?, ?, ?, ?)",
        (batch_id, user_id, payload, int(time.time())),
    )
    conn.commit()


def load_batch(user_id: int, batch_id: str) -> dict | None:
    if using_cloud():
        from api.cloud_store import load_batch as cloud_load_batch
        return cloud_load_batch(user_id, batch_id)
    conn = connect()
    row = conn.execute(
        "SELECT payload FROM batches WHERE id = ? AND user_id = ?",
        (batch_id, user_id),
    ).fetchone()
    if row is None:
        return None
    import json

    return json.loads(row["payload"])


def ensure_company(user: dict) -> dict:
    if using_cloud():
        from api.cloud_store import ensure_company as cloud_ensure_company
        return cloud_ensure_company(user)
    conn = connect()
    row = conn.execute("SELECT * FROM companies WHERE user_id = ?", (user["id"],)).fetchone()
    if row:
        return dict(row)
    code = user.get("company_code") or ("co-" + secrets.token_hex(3))
    conn.execute(
        "INSERT INTO companies (user_id, code, legal_name, home_country) VALUES (?, ?, ?, ?)",
        (user["id"], code, user["business_name"], user.get("home_country") or "Nigeria"),
    )
    conn.execute("UPDATE users SET company_code = ? WHERE id = ?", (code, user["id"]))
    conn.commit()
    return dict(conn.execute("SELECT * FROM companies WHERE user_id = ?", (user["id"],)).fetchone())


def _ensure_reviews(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            chat_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            payload TEXT,
            execution_note TEXT
        )
        """
    )
    for column, kind in (("payload", "TEXT"), ("execution_note", "TEXT"), ("company_id", "TEXT")):
        try:
            conn.execute(f"ALTER TABLE human_reviews ADD COLUMN {column} {kind}")
        except Exception:
            pass


def queue_human_review(kind: str, summary: str, chat_id: str | None = None, detail: str = "", payload: dict | None = None, company_id: str | None = None) -> dict:
    import json

    if company_id is None and chat_id:
        for business in company_businesses():
            if str(chat_id) in {str(item) for item in business.get("telegram_chat_ids") or []}:
                company_id = business["id"]
                break
    if using_cloud():
        from api.cloud_store import queue_human_review as cloud_queue
        return cloud_queue(kind, summary, chat_id, detail, payload, company_id)
    conn = connect()
    _ensure_reviews(conn)
    cur = conn.execute(
        "INSERT INTO human_reviews (kind, summary, detail, chat_id, status, created_at, payload, company_id) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
        (kind, summary, detail, chat_id, int(time.time()), json.dumps(payload) if payload else None, company_id),
    )
    conn.commit()
    return {"id": cur.lastrowid, "kind": kind, "status": "pending", "summary": summary}


def list_reviews(company_id: str | None = None) -> list[dict]:
    if using_cloud():
        from api.cloud_store import list_reviews as cloud_list_reviews
        return cloud_list_reviews(company_id)
    conn = connect()
    _ensure_reviews(conn)
    if company_id:
        rows = conn.execute(
            "SELECT * FROM human_reviews WHERE company_id = ? OR company_id IS NULL ORDER BY id DESC LIMIT 30",
            (company_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM human_reviews ORDER BY id DESC LIMIT 30").fetchall()
    return [dict(row) for row in rows]


def get_review(review_id: int, company_id: str | None = None) -> dict | None:
    if using_cloud():
        from api.cloud_store import get_review as cloud_get_review
        return cloud_get_review(review_id, company_id)
    conn = connect()
    _ensure_reviews(conn)
    if company_id:
        row = conn.execute(
            "SELECT * FROM human_reviews WHERE id = ? AND (company_id = ? OR company_id IS NULL)",
            (review_id, company_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM human_reviews WHERE id = ?", (review_id,)).fetchone()
    return dict(row) if row else None


def resolve_review(review_id: int, status: str, execution_note: str | None = None, company_id: str | None = None) -> dict | None:
    if status not in {"approved", "rejected", "executed", "pending"}:
        raise ValueError("Status must be approved, rejected, executed, or pending.")
    if using_cloud():
        from api.cloud_store import resolve_review as cloud_resolve_review
        return cloud_resolve_review(review_id, status, execution_note, company_id)
    conn = connect()
    _ensure_reviews(conn)
    if company_id:
        conn.execute(
            "UPDATE human_reviews SET status = ?, execution_note = ? WHERE id = ? AND company_id = ?",
            (status, execution_note, review_id, company_id),
        )
    else:
        conn.execute(
            "UPDATE human_reviews SET status = ?, execution_note = ? WHERE id = ?",
            (status, execution_note, review_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM human_reviews WHERE id = ?", (review_id,)).fetchone()
    return dict(row) if row else None


def link_telegram(code: str, chat_id: str) -> dict | None:
    import json
    if using_cloud():
        from api.cloud_store import link_telegram as cloud_link_telegram
        return cloud_link_telegram(code, chat_id)
    conn = connect()
    row = conn.execute("SELECT * FROM companies WHERE code = ?", (code.strip(),)).fetchone()
    if row is None:
        return None
    chats = json.loads(row["telegram_chat_ids"] or "[]")
    if str(chat_id) not in chats:
        chats.append(str(chat_id))
    conn.execute("UPDATE companies SET telegram_chat_ids = ? WHERE id = ?", (json.dumps(chats), row["id"]))
    conn.commit()
    updated = dict(conn.execute("SELECT * FROM companies WHERE id = ?", (row["id"],)).fetchone())
    updated["telegram_chat_ids"] = chats
    return updated


def company_businesses() -> list[dict]:
    import json
    if using_cloud():
        from api.cloud_store import company_businesses as cloud_company_businesses
        try:
            return cloud_company_businesses()
        except Exception as exc:  # noqa: BLE001 — a missing Supabase table must not stop the bot
            print(f"[store] companies unavailable: {exc}")
    conn = connect()
    rows = conn.execute("SELECT * FROM companies").fetchall()
    businesses = []
    for row in rows:
        businesses.append({
            "id": row["code"],
            "legal_name": row["legal_name"],
            "home_country": row["home_country"],
            "telegram_chat_ids": json.loads(row["telegram_chat_ids"] or "[]"),
            "inbound_emails": json.loads(row["inbound_emails"] or "[]"),
            "notify_email": row["notify_email"],
            "port_risk_level": row["port_risk_level"] or "normal",
            "parallel_usd_ngn": row["custom_parallel_ngn"],
            "default_currency": "USD",
            "default_incoterms": None,
        })
    return businesses


PORT_BUFFERS = {"normal": 350_000, "elevated": 900_000, "severe": 1_800_000}


def port_risk_level(company_code: str | None = None) -> str:
    """Company override, then the global default of normal."""
    if using_cloud():
        from api.cloud_store import port_risk_level as cloud_port_risk_level
        try:
            return cloud_port_risk_level(company_code)
        except Exception as exc:  # noqa: BLE001 — use the local default if Supabase is down
            print(f"[store] port risk unavailable: {exc}")
    conn = connect()
    if company_code:
        row = conn.execute(
            "SELECT port_risk_level FROM companies WHERE code = ?",
            (company_code,),
        ).fetchone()
        if row and row["port_risk_level"]:
            return row["port_risk_level"]
    row = conn.execute("SELECT level FROM port_risk WHERE id = 1").fetchone()
    return row["level"] if row else "normal"


def set_port_risk(level: str, company_code: str | None = None) -> dict:
    if level not in PORT_BUFFERS:
        raise ValueError("Level must be normal, elevated, or severe.")
    if using_cloud():
        from api.cloud_store import set_port_risk as cloud_set_port_risk
        return cloud_set_port_risk(level, company_code)
    conn = connect()
    if company_code:
        updated = conn.execute(
            "UPDATE companies SET port_risk_level = ? WHERE code = ?",
            (level, company_code),
        )
        conn.commit()
        if updated.rowcount:
            return {"level": level, "buffer_ngn": PORT_BUFFERS[level], "company_id": company_code}
    conn.execute(
        "INSERT INTO port_risk (id, level, updated_at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at",
        (level, int(time.time())),
    )
    conn.commit()
    return {"level": level, "buffer_ngn": PORT_BUFFERS[level]}


def set_company_parallel(company_code: str, rate: float | None) -> None:
    if using_cloud():
        from api.cloud_store import set_company_parallel as cloud_set_company_parallel
        return cloud_set_company_parallel(company_code, rate)
    conn = connect()
    conn.execute(
        "UPDATE companies SET custom_parallel_ngn = ? WHERE code = ?",
        (rate, company_code),
    )
    conn.commit()


def company_parallel(company_code: str | None) -> float | None:
    if not company_code:
        return None
    if using_cloud():
        from api.cloud_store import company_parallel as cloud_company_parallel
        return cloud_company_parallel(company_code)
    conn = connect()
    row = conn.execute(
        "SELECT custom_parallel_ngn FROM companies WHERE code = ?",
        (company_code,),
    ).fetchone()
    if row is None or row["custom_parallel_ngn"] is None:
        return None
    return float(row["custom_parallel_ngn"])


def apply_finance(user_id: int, record_id: str, principal_ngn: float, fee_rate: float = 0.02) -> dict:
    fee = round(principal_ngn * fee_rate, 2)
    conn = connect()
    cur = conn.execute(
        "INSERT INTO finance_requests (user_id, record_id, principal_ngn, fee_ngn, status, created_at) VALUES (?, ?, ?, ?, 'requested', ?)",
        (user_id, record_id, principal_ngn, fee, int(time.time())),
    )
    conn.commit()
    return {"id": cur.lastrowid, "principal_ngn": principal_ngn, "fee_ngn": fee, "status": "requested", "note": "Request recorded. No lender has disbursed funds."}


def escrow_action(user_id: int, record_id: str, amount_ngn: float, action: str) -> dict:
    if action not in {"hold", "release"}:
        raise ValueError("Action must be hold or release.")
    status = "held_on_ledger" if action == "hold" else "released_on_ledger"
    conn = connect()
    cur = conn.execute(
        "INSERT INTO escrow_ledger (user_id, record_id, amount_ngn, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, record_id, amount_ngn, status, int(time.time())),
    )
    conn.commit()
    return {"id": cur.lastrowid, "status": status, "amount_ngn": amount_ngn, "note": "Ledger entry only. No bank balance was moved."}


def save_payout_plan(user_id: int, record_id: str, trucker_account: str, agent_account: str, customs_account: str) -> dict:
    conn = connect()
    cur = conn.execute(
        """
        INSERT INTO payout_plans (user_id, record_id, trucker_account, agent_account, customs_account, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'ready', ?)
        """,
        (user_id, record_id, trucker_account, agent_account, customs_account, int(time.time())),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "status": "ready",
        "note": "Payout instructions saved. No transfer was sent.",
    }
