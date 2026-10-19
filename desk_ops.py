"""Flag resolution, quote matrix, market-rate index, and WhatsApp send."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
RECORDS = ROOT / "state" / "records"

LOCAL_ACCESS_CAP_NGN = 50_000

FLAG_CATALOG = {
    "validity_48h": {
        "title": "48-hr validity",
        "options": {
            "extend_72h": "Extend to 72 hrs",
            "acknowledge_risk": "Acknowledge Risk",
        },
    },
    "uncapped_local_access": {
        "title": "Un-capped Local Access",
        "options": {
            "cap_50000": "Set Cap at ₦50,000",
            "pass_through": "Pass-Through to Client",
        },
    },
    "gate_in_70": {
        "title": "70% Gate-In Payment",
        "options": {
            "split_50_50": "Negotiate 50/50 Split",
            "accept_terms": "Accept Terms",
        },
    },
}

TELEGRAM_CODES = {
    "1a": ("validity_48h", "extend_72h"),
    "1b": ("validity_48h", "acknowledge_risk"),
    "2a": ("uncapped_local_access", "cap_50000"),
    "2b": ("uncapped_local_access", "pass_through"),
    "3a": ("gate_in_70", "split_50_50"),
    "3b": ("gate_in_70", "accept_terms"),
}


class WhatsAppSend(BaseModel):
    to: str = Field(description="E.164 digits, no plus, for the WhatsApp Cloud API.")
    body: str
    priority: str = "normal"


class FlagResolution(BaseModel):
    flag_id: str
    option: str
    actor: str = "desk"


class ScrapedTerminalStatus(BaseModel):
    terminal: str
    container: str
    vessel_name: str | None = None
    discharge_date: str | None = None
    yard_location: str | None = None
    free_days_allowed: int | None = None
    free_hours_remaining: float | None = None
    demurrage_liability_ngn: float = 0
    found: bool = False
    source: str = ""
    error: str | None = None


class QuoteMatrixRequest(BaseModel):
    record_ids: list[str] = Field(min_length=1, max_length=3)
    agreed_freight_ngn: float | None = None
    equipment: str = "40ft"
    mode: str = "ocean"


def _blob(record: dict) -> str:
    try:
        return json.dumps(record, default=str).lower()
    except TypeError:
        return ""


def _lines(record: dict) -> list[dict]:
    return [item for item in (record.get("line_items") or []) if isinstance(item, dict)]


def detect_operational_flags(record: dict) -> list[dict]:
    """Open hazard flags still waiting on an operator choice."""
    text = _blob(record)
    resolved = {item.get("flag_id") for item in (record.get("flag_resolutions") or [])}
    found = []

    validity = str((record.get("commercial") or {}).get("valid_until") or "")
    short = "48" in validity.lower() or "48-hr" in text or "48 hr" in text or "48 hour" in text
    if short:
        found.append("validity_48h")

    access_lines = [
        item for item in _lines(record)
        if re.search(r"local access|bridge|access road", str(item.get("description") or ""), re.I)
    ]
    if access_lines and not any(float(item.get("amount") or 0) <= LOCAL_ACCESS_CAP_NGN for item in access_lines):
        found.append("uncapped_local_access")
    elif "un-capped" in text or "uncapped" in text or "local access" in text and "cap" not in text:
        if "uncapped_local_access" not in found and ("local access" in text or "bridge" in text):
            found.append("uncapped_local_access")

    payment = str((record.get("commercial") or {}).get("payment_terms") or "")
    if "70%" in text or "70 %" in text or re.search(r"gate[\s-]?in", payment + " " + text):
        if "70" in text or "70%" in payment:
            found.append("gate_in_70")

    open_flags = []
    for flag_id in found:
        if flag_id in resolved:
            continue
        spec = FLAG_CATALOG[flag_id]
        open_flags.append({
            "flag_id": flag_id,
            "title": spec["title"],
            "options": [{"id": key, "label": label} for key, label in spec["options"].items()],
        })
    return open_flags


def _sum_lines(record: dict) -> float:
    return round(sum(float(item.get("amount") or 0) for item in _lines(record)), 2)


def _set_ngn_total(record: dict, total: float) -> float:
    commercial = record.setdefault("commercial", {})
    currency = str(commercial.get("currency") or "NGN").upper()
    commercial["total_amount"] = total
    fx = record.setdefault("fx", {})
    cbn = fx.setdefault("cbn", {})
    if currency == "NGN":
        cbn["NGN"] = total
        return total
    rate = float(cbn.get("usd_ngn") or 0)
    ngn = round(total * rate, 2) if currency == "USD" and rate else float(cbn.get("NGN") or total)
    cbn["NGN"] = ngn
    return ngn


def _extend_validity(record: dict) -> str:
    commercial = record.setdefault("commercial", {})
    start = datetime.now(timezone.utc)
    raw = commercial.get("quote_date")
    if raw:
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except ValueError:
            start = datetime.now(timezone.utc)
    until = start + timedelta(hours=72)
    commercial["valid_until"] = until.date().isoformat()
    return commercial["valid_until"]


def _cap_local_access(record: dict) -> bool:
    changed = False
    for item in _lines(record):
        if re.search(r"local access|bridge|access road", str(item.get("description") or ""), re.I):
            amount = float(item.get("amount") or 0)
            if amount > LOCAL_ACCESS_CAP_NGN or amount == 0:
                item["amount"] = LOCAL_ACCESS_CAP_NGN
                item["capped"] = True
                changed = True
    if not changed:
        record.setdefault("line_items", []).append({
            "description": "Local access (capped)",
            "category": "destination",
            "amount": LOCAL_ACCESS_CAP_NGN,
            "capped": True,
        })
    return True


def _split_gate_in(record: dict) -> bool:
    """An installment change does not change the invoice's charge amounts."""
    record.setdefault("commercial", {})["payment_terms"] = "Proposed 50/50 gate-in split; carrier confirmation required"
    return False


def resolve_flag(record: dict, flag_id: str, option: str, actor: str = "desk") -> dict:
    spec = FLAG_CATALOG.get(flag_id)
    if spec is None or option not in spec["options"]:
        raise ValueError(f"Unknown flag action {flag_id}:{option}")
    record.pop("desk_review", None)
    numerical = False
    note = spec["options"][option]
    if flag_id == "validity_48h" and option == "extend_72h":
        note = f"Validity extended to {_extend_validity(record)}"
    elif flag_id == "uncapped_local_access" and option == "cap_50000":
        _cap_local_access(record)
        numerical = True
        note = f"Local access capped at NGN {LOCAL_ACCESS_CAP_NGN:,.0f}"
    elif flag_id == "uncapped_local_access" and option == "pass_through":
        record.setdefault("commercial", {})["local_access"] = "pass-through"
    elif flag_id == "gate_in_70" and option == "split_50_50":
        numerical = _split_gate_in(record)
        note = "Proposed 50/50 gate-in split recorded; confirm with the carrier"
    elif option in {"acknowledge_risk", "accept_terms"}:
        note = spec["options"][option]

    ngn = None
    if numerical:
        ngn = _set_ngn_total(record, _sum_lines(record))
        from market import enrich
        enrich(record, record.get("business"))
    record.setdefault("flag_resolutions", []).append({
        "flag_id": flag_id,
        "option": option,
        "label": note,
        "actor": actor,
        "at": datetime.now(timezone.utc).isoformat(),
        "recalculated": numerical,
    })
    record["open_flags"] = detect_operational_flags(record)
    return {"note": note, "recalculated": numerical, "ngn_total": ngn, "open_flags": record["open_flags"]}


def load_record(record_id: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id or ""):
        return None
    path = RECORDS / f"{record_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_record(record_id: str, record: dict, chat_id: str | None = None) -> str | None:
    RECORDS.mkdir(parents=True, exist_ok=True)
    (RECORDS / f"{record_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        from supabase_sync import sync_quote

        return sync_quote(record, record_id, chat_id=chat_id)
    except Exception as exc:  # noqa: BLE001 — local file remains the desk copy
        record["sync_error"] = str(exc)
        return None


def _lane_key(record: dict) -> str:
    movement = record.get("movement") or {}
    origin = (movement.get("origin") or {}).get("location_name") or "?"
    dest = (movement.get("destination") or {}).get("location_name") or "?"
    return f"{origin} -> {dest}"


def _risk(record: dict) -> str:
    flags = detect_operational_flags(record)
    if any(item["flag_id"] == "uncapped_local_access" for item in flags):
        return "red"
    if flags:
        return "yellow"
    return "green"


def _landed_ngn(record: dict) -> float:
    cbn = (record.get("fx") or {}).get("cbn") or {}
    if cbn.get("NGN"):
        return float(cbn["NGN"])
    commercial = record.get("commercial") or {}
    if str(commercial.get("currency") or "").upper() == "NGN":
        return float(commercial.get("total_amount") or 0)
    return float(commercial.get("total_amount") or 0)


def comparison_matrix(records: list[dict]) -> dict:
    if not records or len(records) > 3:
        raise ValueError("Compare 1 to 3 quotes for the same lane.")
    columns = []
    for record in records:
        commercial = record.get("commercial") or {}
        movement = record.get("movement") or {}
        demurrage = record.get("demurrage") or {}
        columns.append({
            "vendor": commercial.get("vendor_name") or "Carrier",
            "reference": commercial.get("quote_reference_id"),
            "lane": _lane_key(record),
            "landed_cost_ngn": _landed_ngn(record),
            "ocean_freight": commercial.get("origin_charges"),
            "local_port_charges": commercial.get("destination_charges"),
            "duty": commercial.get("customs_and_tax"),
            "transit_days": movement.get("est_transit_days"),
            "free_days": demurrage.get("free_days"),
            "demurrage_daily_ngn": demurrage.get("daily_rate_ngn") or demurrage.get("buffer_ngn"),
            "risk": _risk(record),
            "open_flags": [item["title"] for item in detect_operational_flags(record)],
        })
    lanes = {item["lane"] for item in columns}
    return {
        "lane": next(iter(lanes)) if len(lanes) == 1 else "mixed lanes",
        "columns": columns,
        "lowest_landed_ngn": min(item["landed_cost_ngn"] for item in columns),
    }


def _db() -> sqlite3.Connection:
    from api.store import connect

    conn = connect()
    conn.execute(
        """
        create table if not exists market_rates (
            id integer primary key autoincrement,
            lane text not null,
            equipment text not null,
            mode text not null,
            freight_ngn real not null,
            created_at text not null
        )
        """
    )
    return conn


def save_market_rate(lane: str, freight_ngn: float, equipment: str = "40ft", mode: str = "ocean") -> dict:
    """Store an anonymized agreed freight figure. Vendor names are not written."""
    row = {
        "lane": lane.strip(),
        "equipment": equipment,
        "mode": mode,
        "freight_ngn": round(float(freight_ngn), 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not row["lane"] or row["freight_ngn"] <= 0:
        raise ValueError("A lane and a positive agreed freight are required.")
    with _db() as conn:
        conn.execute(
            "insert into market_rates (lane, equipment, mode, freight_ngn, created_at) values (?, ?, ?, ?, ?)",
            (row["lane"], row["equipment"], row["mode"], row["freight_ngn"], row["created_at"]),
        )
    _push_market_rate(row)
    return row


def _push_market_rate(row: dict) -> None:
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return
    try:
        from supabase_sync import _request

        _request("POST", "market_rates", {
            "lane": row["lane"],
            "equipment": row["equipment"],
            "mode": row["mode"],
            "freight_ngn": row["freight_ngn"],
        })
    except Exception:
        return


def lane_benchmark(lane: str, equipment: str = "40ft") -> dict:
    with _db() as conn:
        rows = conn.execute(
            "select freight_ngn from market_rates where lane = ? and equipment = ?",
            (lane, equipment),
        ).fetchall()
    figures = [float(row["freight_ngn"]) for row in rows]
    average = round(sum(figures) / len(figures), 2) if figures else None
    headline = None
    if average is not None:
        headline = f"Current Average {equipment} Rate {lane}: ₦{average:,.0f}"
    return {"lane": lane, "equipment": equipment, "samples": len(figures), "average_ngn": average, "headline": headline}


def matrix_files(matrix: dict, business_name: str) -> tuple[bytes, bytes]:
    from io import BytesIO

    from api.exports import new_pdf
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "Matrix"
    headers = [
        "Vendor", "Lane", "Landed NGN", "Transit days", "Free days",
        "Demurrage daily NGN", "Risk", "Open flags",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0B3954")
    for column in matrix["columns"]:
        sheet.append([
            column["vendor"], column["lane"], column["landed_cost_ngn"],
            column["transit_days"], column["free_days"], column["demurrage_daily_ngn"],
            column["risk"], "; ".join(column["open_flags"]),
        ])
    buffer = BytesIO()
    book.save(buffer)

    pdf = new_pdf()
    pdf.add_page()
    pdf.set_font("Desk", "B", 14)
    pdf.cell(0, 10, f"{business_name} quote matrix", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Desk", "", 10)
    pdf.cell(0, 8, f"Lane: {matrix['lane']}", new_x="LMARGIN", new_y="NEXT")
    for column in matrix["columns"]:
        pdf.multi_cell(
            180,
            6,
            f"{column['vendor']}: landed NGN {column['landed_cost_ngn']:,.0f}; "
            f"transit {column['transit_days'] or '-'}; free days {column['free_days'] or '-'}; "
            f"risk {column['risk']}",
        )
    return buffer.getvalue(), bytes(pdf.output())


def _wa_chat_id(to: str) -> str:
    """Trial instances may message only WAAPI_CHAT_ID. That value wins when it is set."""
    pinned = (os.environ.get("WAAPI_CHAT_ID") or "").strip()
    if pinned:
        return pinned if "@" in pinned else f"{re.sub(r'\\D', '', pinned)}@c.us"
    raw = (to or "").strip()
    if "@" in raw:
        return raw
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "234" + digits[1:]
    if len(digits) < 8:
        raise ValueError("WhatsApp recipient needs a country code, for example 2348068512870.")
    return f"{digits}@c.us"


def send_whatsapp(payload: WhatsAppSend) -> dict:
    """Send through WaAPI instance client action send-message."""
    import urllib.error

    token = os.environ.get("WAAPI_TOKEN") or ""
    instance = os.environ.get("WAAPI_INSTANCE_ID") or ""
    if not token or not instance:
        return {"sent": False, "reason": "WAAPI_TOKEN or WAAPI_INSTANCE_ID is not set."}
    chat_id = _wa_chat_id(payload.to)
    body = {"chatId": chat_id, "message": payload.body[:4000], "skipNumberCheck": True}
    request = urllib.request.Request(
        f"https://waapi.app/api/v1/instances/{instance}/client/action/send-message",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        return {"sent": False, "reason": detail or str(exc), "chat_id": chat_id}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": str(exc), "chat_id": chat_id}
    inner = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    if raw.get("status") == "error" or inner.get("status") == "error":
        return {"sent": False, "reason": inner.get("message") or raw.get("message") or "WaAPI did not send the message.", "chat_id": chat_id}
    message_id = ((inner.get("data") or {}).get("id") if isinstance(inner.get("data"), dict) else None) or inner.get("id")
    return {"sent": True, "id": message_id, "chat_id": chat_id}
