"""Private, durable operational state with compare-and-swap updates.

Cloud deployments use Supabase; local development uses the account database.
Revision checks make webhook claims and expiring link codes single-consumer.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote
from api import store


def connect():
    conn = store.connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS operation_state (
      namespace TEXT NOT NULL, key TEXT NOT NULL, company_id TEXT,
      payload TEXT NOT NULL, revision INTEGER NOT NULL, updated_at REAL NOT NULL,
      PRIMARY KEY(namespace,key))""")
    conn.execute("CREATE TABLE IF NOT EXISTS intake_receipts (receipt TEXT PRIMARY KEY, user_id INTEGER NOT NULL)")
    return conn


def _decode(row):
    if not row: return None
    result = dict(row)
    if isinstance(result.get("payload"), str): result["payload"] = json.loads(result["payload"])
    return result


def get(namespace, key):
    if store.using_cloud():
        from supabase_sync import _request
        rows = _request("GET", f"operation_state?namespace=eq.{quote(namespace, safe='')}&key=eq.{quote(key, safe='')}&limit=1", None)
        return _decode(rows[0]) if rows else None
    with connect() as conn:
        return _decode(conn.execute("SELECT * FROM operation_state WHERE namespace=? AND key=?", (namespace, key)).fetchone())


def put(namespace, key, payload, company_id=None, expected=None):
    """expected=0 creates only; positive revisions update only that version."""
    store._require_durable()
    if store.using_cloud():
        from supabase_sync import _request
        return _decode(_request("POST", "rpc/put_operation_state", {"p_namespace": namespace, "p_key": key, "p_payload": payload, "p_company_id": company_id, "p_expected": expected}))
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT revision FROM operation_state WHERE namespace=? AND key=?", (namespace, key)).fetchone()
        revision = current["revision"] if current else 0
        if expected is not None and revision != expected: return None
        conn.execute("INSERT INTO operation_state VALUES (?,?,?,?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET company_id=excluded.company_id,payload=excluded.payload,revision=excluded.revision,updated_at=excluded.updated_at", (namespace, key, company_id, json.dumps(payload), revision + 1, time.time()))
        return _decode(conn.execute("SELECT * FROM operation_state WHERE namespace=? AND key=?", (namespace, key)).fetchone())


def listing(namespace, company_id=None, status=None, limit=200):
    limit = max(1, min(int(limit), 500))
    if store.using_cloud():
        from supabase_sync import _request
        path = f"operation_state?namespace=eq.{quote(namespace, safe='')}&order=updated_at.asc&limit={limit}"
        if company_id is not None: path += f"&company_id=eq.{quote(company_id, safe='')}"
        if status is not None: path += f"&payload->>status=eq.{quote(status, safe='')}"
        return [_decode(row) for row in _request("GET", path, None)]
    with connect() as conn:
        sql, values = "SELECT * FROM operation_state WHERE namespace=?", [namespace]
        if company_id is not None: sql += " AND company_id=?"; values.append(company_id)
        if status is not None: sql += " AND json_extract(payload,'$.status')=?"; values.append(status)
        return [_decode(row) for row in conn.execute(sql + " ORDER BY updated_at ASC LIMIT ?", (*values, limit))]


def charge_once(user_id, receipt):
    """Quota debit and receipt are one transaction, including provider retries."""
    store._require_durable()
    if store.using_cloud():
        from supabase_sync import _request
        if not _request("POST", "rpc/charge_intake_once", {"p_user_id": user_id, "p_receipt": receipt}):
            raise PermissionError("Your parse allowance is used up. Open Settings to add capacity.")
        return
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT user_id FROM intake_receipts WHERE receipt=?", (receipt,)).fetchone()
        if existing:
            if existing["user_id"] != user_id: raise PermissionError("Receipt belongs to another workspace.")
            return
        if not conn.execute("UPDATE users SET quota_remaining=quota_remaining-1 WHERE id=? AND quota_remaining>0", (user_id,)).rowcount:
            raise PermissionError("Your parse allowance is used up. Open Settings to add capacity.")
        conn.execute("INSERT INTO intake_receipts VALUES (?,?)", (receipt, user_id))


def was_charged(user_id, receipt):
    if store.using_cloud():
        from supabase_sync import _request
        rows = _request("GET", f"intake_receipts?receipt=eq.{quote(receipt, safe='')}&user_id=eq.{int(user_id)}&select=receipt&limit=1", None)
        return bool(rows)
    with connect() as conn:
        return bool(conn.execute("SELECT 1 FROM intake_receipts WHERE receipt=? AND user_id=?", (receipt, user_id)).fetchone())


def first_chat_job(chat):
    """Keep replies and follow-up context in received order, including retries."""
    if store.using_cloud():
        from supabase_sync import _request
        rows = _request("GET", "operation_state?namespace=eq.wa_jobs&payload->>status=in.(pending,processing,sending)"
                        f"&payload->>chat=eq.{quote(chat, safe='')}&order=payload->received_at.asc,key.asc&limit=1", None)
        return _decode(rows[0]) if rows else None
    with connect() as conn:
        return _decode(conn.execute("SELECT * FROM operation_state WHERE namespace='wa_jobs' AND json_extract(payload,'$.chat')=? AND json_extract(payload,'$.status') IN ('pending','processing','sending') ORDER BY json_extract(payload,'$.received_at'),key LIMIT 1", (chat,)).fetchone())
