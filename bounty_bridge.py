"""Private bounty integration. Persist references and decisions, never send quote bodies."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()


@contextmanager
def database():
    path = Path(os.environ.get("BOUNTY_BRIDGE_DB", Path(__file__).parent / "state" / "bounty-bridge.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS extracts (id TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL, company_id TEXT NOT NULL,
                digest TEXT NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                delivered INTEGER NOT NULL DEFAULT 0, decided_at TEXT,
                UNIQUE(record_id, company_id, digest, type))""")
            yield db
    finally:
        db.close()


def authorize(token):
    expected = os.environ.get("QUOTE_INTERNAL_TOKEN", "").strip()
    if not expected or not secrets.compare_digest(token or "", expected):
        raise HTTPException(401, "internal token required")


def digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def extract(text, key, parser):
    signature = hashlib.sha256(text.encode()).hexdigest()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT * FROM extracts WHERE id=?", (key,)).fetchone()
        if previous:
            if previous["digest"] != signature:
                raise HTTPException(409, "idempotency key already used for different text")
            return json.loads(previous["response"])
        payload = parser(text).model_dump()
        db.execute("INSERT INTO extracts VALUES (?,?,?)", (key, signature, json.dumps(payload)))
        return payload


def enqueue(record):
    company = os.environ.get("BOUNTY_COMPANY_ID", "").strip()
    if not company or record.get("company_id") != company:
        return None
    ref = secrets.token_hex(16)
    signature = digest(record)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE events SET status='superseded' WHERE record_id=? AND company_id=? AND digest!=? AND status='pending'", (record["record_id"], company, signature))
        db.execute("INSERT OR IGNORE INTO events(id,record_id,company_id,digest,type) VALUES (?,?,?,?,?)", (ref, record["record_id"], company, signature, "quote_ready"))
        row = db.execute("SELECT id FROM events WHERE record_id=? AND company_id=? AND digest=? AND type='quote_ready'", (record["record_id"], company, signature)).fetchone()
        return row["id"]


def load_quote(record_id, company):
    from api.store import using_cloud
    if using_cloud():
        from supabase_sync import get_quote
        return get_quote(record_id, company)
    from desk_ops import load_record
    return load_record(record_id)


class Decision(BaseModel):
    status: Literal["approved", "rejected"]


@router.post("/api/v1/quote-events/{ref}/decision")
def decide(ref: str, body: Decision, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    if not re.fullmatch(r"[a-f0-9]{32}", ref):
        raise HTTPException(404, "event not found")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM events WHERE id=? AND company_id=?", (ref, os.environ.get("BOUNTY_COMPANY_ID", "").strip())).fetchone()
        if row is None:
            raise HTTPException(404, "event not found")
        if row["status"] == body.status:
            return {"id": ref, "status": body.status}
        if row["status"] != "pending":
            raise HTTPException(409, "event already handled or superseded")
        record = load_quote(row["record_id"], row["company_id"])
        if not record or record.get("company_id") != row["company_id"] or digest(record) != row["digest"]:
            raise HTTPException(409, "quote changed or unavailable; review its current version")
        db.execute("UPDATE events SET status=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (body.status, ref))
        return {"id": ref, "status": body.status}


@router.get("/api/v1/quote-events/{ref}")
def event_status(ref: str, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with database() as db:
        row = db.execute("SELECT id,record_id,status,decided_at FROM events WHERE id=? AND company_id=?", (ref, os.environ.get("BOUNTY_COMPANY_ID", "").strip())).fetchone()
        if row is None:
            raise HTTPException(404, "event not found")
        return dict(row)


def deliver_pending(send):
    # Successful sends are marked after delivery. A crash can duplicate a card;
    # its reference and idempotent decision remain the same.
    with database() as db:
        rows = db.execute("SELECT id,type FROM events WHERE delivered=0 AND status='pending' AND company_id=? LIMIT 100", (os.environ.get("BOUNTY_COMPANY_ID", "").strip(),)).fetchall()
    for row in rows:
        if send(row["type"], row["id"]):
            with database() as db:
                db.execute("UPDATE events SET delivered=1 WHERE id=?", (row["id"],))
