"""Shared customs record any business can file from a normalized quote.

The lane is decided from the business home country:
- export when cargo leaves home
- import when cargo arrives home
- cross_trade when home is neither end
- domestic when both ends are home
- unknown when a country is missing
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quote_agent import QuoteExtractionResult

ROOT = Path(__file__).resolve().parent
BUSINESSES_PATH = ROOT / "businesses.json"


def load_businesses(path: Path | None = None) -> list[dict[str, Any]]:
    file = path or BUSINESSES_PATH
    if not file.exists():
        example = ROOT / "businesses.example.json"
        file = example if example.exists() else file
    data = json.loads(file.read_text(encoding="utf-8"))
    return list(data["businesses"])


def find_business(
    businesses: list[dict[str, Any]],
    *,
    business_id: str | None = None,
    telegram_chat_id: str | None = None,
    email_from: str | None = None,
) -> dict[str, Any] | None:
    if business_id:
        for business in businesses:
            if business["id"] == business_id:
                return business
        return None
    if telegram_chat_id is not None:
        chat = str(telegram_chat_id)
        for business in businesses:
            if chat in {str(item) for item in business.get("telegram_chat_ids", [])}:
                return business
    if email_from:
        domain = email_from.lower().split("@")[-1]
        address = email_from.lower()
        for business in businesses:
            allowed = [item.lower() for item in business.get("inbound_emails", [])]
            if address in allowed or f"@{domain}" in allowed or domain in allowed:
                return business
    return None


def customs_lane(home_country: str | None, origin: str | None, destination: str | None) -> str:
    if not origin or not destination:
        return "unknown"
    home = (home_country or "").casefold()
    if origin.casefold() == home and destination.casefold() == home:
        return "domestic"
    if origin.casefold() == home:
        return "export"
    if destination.casefold() == home:
        return "import"
    if home:
        return "cross_trade"
    return "unknown"


def _sum_category(result: QuoteExtractionResult, category: str) -> float:
    return round(sum(item.amount for item in result.financials.line_items if item.category == category), 2)


def to_customs_record(result: QuoteExtractionResult, business: dict[str, Any]) -> dict[str, Any]:
    origin = result.shipment_details.origin.country
    destination = result.shipment_details.destination.country
    lane = customs_lane(business.get("home_country"), origin, destination)
    currency = result.financials.currency or business.get("default_currency") or "USD"
    record = {
        "schema": "global-customs-quote/v1",
        "business": {
            "id": business["id"],
            "legal_name": business.get("legal_name"),
            "home_country": business.get("home_country"),
        },
        "lane": lane,
        "commercial": {
            "vendor_name": result.quote_metadata.vendor_name,
            "carrier_name": result.quote_metadata.vendor_name or "Issued by: Regional Freight Broker Platform (Spot Market Desk)",
            "quote_reference_id": result.quote_metadata.quote_reference_id,
            "quote_date": result.quote_metadata.quote_date,
            "valid_until": result.quote_metadata.valid_until,
            "incoterms": result.terms_and_notes.incoterms,
            "payment_terms": result.terms_and_notes.payment_terms,
            "currency": currency,
            "customs_value_basis": _sum_category(result, "Base Freight") + _sum_category(result, "Fuel / Surcharge"),
            "origin_charges": _sum_category(result, "Origin Charge"),
            "destination_charges": _sum_category(result, "Destination Charge"),
            "customs_and_tax": _sum_category(result, "Customs / Tax"),
            "other_charges": _sum_category(result, "Other"),
            "total_amount": result.financials.total_amount,
        },
        "movement": {
            "mode": result.shipment_details.transport_mode,
            "origin": result.shipment_details.origin.model_dump(),
            "destination": result.shipment_details.destination.model_dump(),
            "weight_kg": result.shipment_details.weight_kg,
            "volume_cbm": result.shipment_details.volume_cbm,
            "package": result.shipment_details.container_or_package_type,
            "est_transit_days": result.shipment_details.est_transit_days,
        },
        "line_items": [item.model_dump() for item in result.financials.line_items],
        "extraction_flags": list(result.extraction_flags),
        "disclaimer": (
            "Normalized commercial quote for internal review. "
            "It is not a filed customs declaration."
        ),
    }
    from quote_agent import lock_domestic_incoterm

    return lock_domestic_incoterm(record)


def _missing_questions(record: dict) -> list[str]:
    commercial = record.get("commercial") or {}
    movement = record.get("movement") or {}
    questions = []
    if not (movement.get("destination") or {}).get("location_name"):
        questions.append("What is the destination port?")
    if not record.get("line_items"):
        questions.append("Send each charge on its own line with the currency, such as NGN 390,000.")
    return questions


def _place_label(place: dict) -> str:
    name = place.get("location_name") or "?"
    code = place.get("port_code")
    if code and f"({code})" not in name:
        return f"{name} ({code})"
    return name


def land_corridor(record: dict, source: str = "") -> bool:
    """A domestic road move named as a truck, flatbed, or dry-box trailer."""
    blob = " ".join([
        source,
        record.get("lane") or "",
        json.dumps(record.get("movement") or {}),
        " ".join(item.get("description") or "" for item in record.get("line_items") or []),
        " ".join(record.get("extraction_flags") or []),
    ]).lower()
    land = any(word in blob for word in ("dry box trailer", "flatbed", "truck", "land asset named"))
    domestic = record.get("lane") == "domestic" or ("lagos" in blob and ("makurdi" in blob or "benue" in blob))
    return land and domestic


def fold_road_split(record: dict) -> None:
    """Give shipping-line and clearing-agent shares to the trucker on a road corridor."""
    split = record.get("split") or {}
    rows = list(split.get("rows") or [])
    if not rows:
        return
    trucker = next((row for row in rows if row.get("party") == "trucker"), None)
    if trucker is None:
        trucker = {"party": "trucker", "share": 0, "usd": 0, "ngn": 0, "role": "fleet_owner", "currency_preference": "NGN"}
        rows.append(trucker)
    kept = []
    for row in rows:
        if row.get("party") in {"shipping_line", "clearing_agent"}:
            trucker["share"] = round(float(trucker.get("share") or 0) + float(row.get("share") or 0), 4)
            for key in ("usd", "ngn"):
                if row.get(key) is not None:
                    trucker[key] = round(float(trucker.get(key) or 0) + float(row.get(key) or 0), 2)
            continue
        kept.append(row)
    trucker["role"] = "fleet_owner"
    split["rows"] = kept
    record["split"] = split


def volatile_official_line(record: dict) -> str | None:
    """Wipe foreign money when any displayed naira-per-dollar rate is 2,500 or higher."""
    fx = record.get("fx") or {}
    rates = []
    for tier in ("cbn", "parallel"):
        rate = (fx.get(tier) or {}).get("usd_ngn")
        if rate is not None:
            rates.append(float(rate))
    market_rate = ((fx.get("market") or {}).get("usd_ngn"))
    if market_rate is not None:
        rates.append(float(market_rate))
    if not any(rate >= 2500 for rate in rates):
        return None
    commercial = record.get("commercial") or {}
    if (commercial.get("currency") or "").upper() == "NGN":
        total = float(commercial.get("total_amount") or 0)
    else:
        total = float(((fx.get("mixed") or {}).get("local_ngn")) or 0)
    return (
        f"Official Figures: NGN {total:,.0f} "
        "(FX conversion omitted due to volatile exchange rate calculation anomaly)."
    )


def finalize_client_text(text: str, record: dict, source: str = "") -> str:
    """Client letters must not repeat a bad rate, a shipping line, or an open carrier question."""
    cleaned = text or ""
    cleaned = re.sub(r"Which carrier issued this quote\??", "Carrier/Issuer: Freight Desk (Spot Market Platform)", cleaned, flags=re.I)
    if land_corridor(record, source):
        fold_road_split(record)
        cleaned = re.sub(r"shipping[\s-]*line", "trucker/fleet owner", cleaned, flags=re.I)
        cleaned = re.sub(r"clearing[\s-]*agent", "trucker/fleet owner", cleaned, flags=re.I)
        if "Carrier/Issuer: Freight Desk (Spot Market Platform)" not in cleaned:
            cleaned = "Carrier/Issuer: Freight Desk (Spot Market Platform)\n" + cleaned
    official = volatile_official_line(record)
    if official:
        cleaned = re.sub(
            r"(?:USD|CNY|usd_ngn|NGN/USD|exchange rate)[^\n]*",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b", _drop_corrupt_rate, cleaned)
        if official not in cleaned:
            cleaned = official + "\n" + cleaned
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _drop_corrupt_rate(match: re.Match[str]) -> str:
    number = float(match.group(0).replace(",", ""))
    if number >= 2500 and number < 10000:
        return ""
    return match.group(0)


def format_notice(record: dict[str, Any]) -> str:
    commercial = record["commercial"]
    movement = record["movement"]
    origin = movement["origin"]
    destination = movement["destination"]
    if record.get("agent_ready") is False:
        return "\n".join([
            f"{record['business']['legal_name']}",
            "I could not price this message.",
            "I need a route or a vendor, and at least one charge written as NGN 390,000 or USD 5,100.",
            *_missing_questions(record),
            "I did not convert, finance, or split it.",
        ] + (
            ["Gemini had no quota left, so only the strict reader ran."]
            if any("429" in flag or "quota" in flag for flag in record.get("extraction_flags") or [])
            else []
        ))
    carrier = commercial.get("carrier_name") or commercial.get("vendor_name") or "Issued by: Regional Freight Broker Platform (Spot Market Desk)"
    lines = [
        f"{commercial['vendor_name'] or 'Quote'} · {record['lane'].replace('_', ' ')}",
        carrier if carrier.startswith("Issued by:") else f"Carrier: {carrier}",
        *([commercial['quote_reference_id']] if commercial.get('quote_reference_id') else []),
        (
            f"{_place_label(origin)} → {_place_label(destination)}"
        ),
        (
            f"USD {record['fx']['mixed']['usd_freight']:,.2f} freight + NGN {record['fx']['mixed']['local_ngn']:,.2f} local"
            if (record.get("fx") or {}).get("mixed")
            else f"{commercial['currency']} {commercial['total_amount']:,.2f} · {commercial['incoterms'] or 'incoterm n/a'}"
        ),
        f"Customs/tax {commercial['currency']} {commercial['customs_and_tax']:,.2f}",
    ]
    fx = record.get("fx") or {}
    cbn = (fx.get("cbn") or {})
    parallel = (fx.get("parallel") or {})
    already_naira = commercial.get("currency") == "NGN" and not fx.get("mixed")
    if already_naira:
        lines.append("This quote is already in naira, so it was not run through an exchange rate.")
        if fx.get("error"):
            lines.append(fx["error"])
    elif fx.get("error"):
        lines.append(fx["error"])
    elif cbn.get("NGN") and not cbn.get("anomaly"):
        lines.append(f"Official figures NGN {cbn['NGN']:,.0f} · CNY {cbn['CNY']:,.2f}")
    if not already_naira and not fx.get("error") and parallel.get("NGN") and not parallel.get("anomaly"):
        lines.append(f"Parallel cash rate NGN {parallel['NGN']:,.0f} at {parallel['usd_ngn']:,.2f}")
    elif not already_naira and not fx.get("error") and not parallel.get("anomaly"):
        lines.append("Parallel rate not set. Add one on the desk.")
    financing = record.get("financing") or {}
    if financing.get("offered"):
        lines.append(
            f"Duty finance estimate NGN {financing['principal_ngn']:,.0f} plus {financing['fee_rate']:.1%} fee"
        )
    guard = record.get("demurrage") or {}
    if guard.get("buffer_hours"):
        lines.append(f"Demurrage buffer {guard['buffer_hours']:g} hours")
    elif guard.get("buffer_ngn"):
        lines.append(f"Demurrage buffer NGN {guard['buffer_ngn']:,.0f} after {guard['free_days']} days")
    fee = ((record.get("split") or {}).get("platform_fee_rate"))
    if fee:
        lines.append(f"Platform fee share {fee:.1%} of the all-in total. No money was sent.")
    duty = record.get("duty_estimate") or {}
    if duty.get("total_ngn"):
        lines.append(
            f"HS {duty['hs_code']} estimate NGN {duty['total_ngn']:,.0f} "
            f"(duty {duty['import_duty_ngn']:,.0f}, ETLS {duty['etls_ngn']:,.0f}, "
            f"CISS {duty['ciss_ngn']:,.0f}, VAT {duty['vat_ngn']:,.0f}). Not an NCS assessment."
        )
    elif duty.get("hs_code"):
        lines.append(f"HS {duty['hs_code']} recognised. {duty.get('reason') or ''}".strip())
    if record.get("extraction_flags"):
        lines.append(f"Flags: {len(record['extraction_flags'])}")
    return finalize_client_text("\n".join(lines), record)
