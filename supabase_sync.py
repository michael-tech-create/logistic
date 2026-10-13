"""Insert a parsed quote into Supabase when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
        "User-Agent": "logistics-quote-api/1.0",
    }


def _request(method: str, path: str, payload) -> list | dict:
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    headers = _headers()
    data = None
    if payload is not None and method != "DELETE":
        data = json.dumps(payload).encode()
    else:
        headers.pop("Content-Type", None)
        headers.pop("Prefer", None)
    request = urllib.request.Request(f"{base}/rest/v1/{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else []


def sync_quote(record: dict, record_id: str, *, chat_id: str | None = None, telegram_user_id: str | None = None) -> str | None:
    """Upsert the quote, replace its lines and splits, and return the Supabase row id."""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return None
    commercial = record.get("commercial") or {}
    fx = record.get("fx") or {}
    official = fx.get("cbn") or {}
    row = {
        "record_id": record_id,
        "telegram_user_id": telegram_user_id,
        "chat_id": chat_id,
        "status": "pending",
        "vendor_name": commercial.get("vendor_name"),
        "quote_reference_id": commercial.get("quote_reference_id"),
        "lane": record.get("lane"),
        "currency": commercial.get("currency"),
        "total_amount": commercial.get("total_amount"),
        "usd_amount": official.get("USD"),
        "ngn_amount": official.get("NGN"),
        "cny_amount": official.get("CNY"),
        "usd_ngn_rate": official.get("usd_ngn"),
        "usd_cny_rate": None,
        "company_id": record.get("company_id") or (record.get("business") or {}).get("id"),
        "payload": record,
    }
    saved = _request("POST", "quotes?on_conflict=record_id", row)
    quote = saved[0] if isinstance(saved, list) and saved else {}
    quote_id = quote.get("id")
    if not quote_id:
        return None
    _request("DELETE", f"line_items?quote_id=eq.{quote_id}", [])
    items = []
    for item in record.get("line_items") or []:
        items.append({
            "quote_id": quote_id,
            "description": item.get("description"),
            "category": item.get("category"),
            "currency": commercial.get("currency"),
            "amount": item.get("amount"),
        })
    if items:
        _request("POST", "line_items", items)
    _request("DELETE", f"quote_splits?quote_id=eq.{quote_id}", [])
    splits = []
    cny = official.get("CNY") or 0
    for part in ((record.get("split") or {}).get("rows") or []):
        share = part.get("share") or 0
        splits.append({
            "quote_id": quote_id,
            "party": part.get("party"),
            "share": share,
            "currency": part.get("currency_preference"),
            "usd_amount": part.get("usd"),
            "ngn_amount": part.get("ngn"),
            "cny_amount": round(float(cny) * float(share), 2) if cny else None,
        })
    if splits:
        _request("POST", "quote_splits", splits)
    return quote_id


def delete_quote(record_id: str, company_id: str) -> bool:
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return False
    _request(
        "DELETE",
        f"quotes?record_id=eq.{urllib.parse.quote(record_id, safe='')}&company_id=eq.{urllib.parse.quote(company_id, safe='')}",
        None,
    )
    return True


def list_quotes(company_id: str) -> list[dict] | None:
    """Quotes for one company. None means Supabase is not configured."""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return None
    if not company_id:
        return []
    rows = _request(
        "GET",
        f"quotes?company_id=eq.{urllib.parse.quote(company_id)}&select=record_id,payload&order=created_at.desc&limit=20",
        None,
    )
    records = []
    for row in rows if isinstance(rows, list) else []:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload["record_id"] = row.get("record_id")
        payload["company_id"] = company_id
        records.append(payload)
    return records
