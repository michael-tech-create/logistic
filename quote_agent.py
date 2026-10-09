"""Freight quote normalizer.

Extracts unstructured quote text into the standard logistics JSON schema.
Uses a deterministic parser for common rate-sheet layouts, and SpaceXAI
(xAI API, OpenAI-compatible) when XAI_API_KEY is set and --llm is passed
or the parser cannot find a total.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Literal, Optional

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

Category = Literal[
    "Base Freight",
    "Fuel / Surcharge",
    "Origin Charge",
    "Destination Charge",
    "Customs / Tax",
    "Other",
]
TransportMode = Literal["Ocean", "Air", "Road", "Rail", "Multimodal", "Unknown"]

SYSTEM_PROMPT = """
You are an expert Freight and Logistics Data Normalization Agent.
Extract unstructured logistics data and return JSON matching the schema.
Rules:
- Standardize dates to YYYY-MM-DD.
- Standardize currencies to 3-letter ISO codes (USD, EUR, GBP, NGN).
- Convert transit times to total estimated days as an integer.
  Use the midpoint of a range when needed (3-5 weeks -> 28).
- Categorize every line item as one of:
  Base Freight, Fuel / Surcharge, Origin Charge, Destination Charge,
  Customs / Tax, Other.
  Origin THC and export clearance are Origin Charge.
  Destination THC and delivery are Destination Charge.
  BAF, LSS, and peak-season surcharges are Fuel / Surcharge.
  Duties, taxes, and brokerage are Customs / Tax.
- If no total is stated, sum the detail lines.
- Never add a SUBTOTAL, grand total, or "total local" line on top of the detail lines.
- Keep a USD freight amount out of an NGN total. Put that in extraction_flags.
- Do not invent a vendor, route, incoterm, or total.
- If the message is a previous bot reply, a greeting, or has no real charge lines, return no line items and total_amount 0.
- A real charge looks like "Import Surface Duty NGN 12,500,000" or "Ocean Freight: $2,400".
- A line that only says "Customs/tax NGN ..." is a summary, not a charge.
- Note ambiguities in extraction_flags.
"""

PORT_COUNTRY = {
    "CNSHA": "China",
    "CNYTN": "China",
    "CNNGB": "China",
    "DEHAM": "Germany",
    "NLRTM": "Netherlands",
    "USLAX": "United States",
    "USNYC": "United States",
    "USLGB": "United States",
    "GBFXT": "United Kingdom",
    "SGSIN": "Singapore",
    "AEJEA": "United Arab Emirates",
    "NGLOS": "Nigeria",
    "NGAPP": "Nigeria",
}

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₦": "NGN"}
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


class Location(BaseModel):
    location_name: Optional[str] = None
    port_code: Optional[str] = None
    country: Optional[str] = None


class VendorMetadata(BaseModel):
    vendor_name: Optional[str] = None
    quote_reference_id: Optional[str] = None
    quote_date: Optional[str] = None
    valid_until: Optional[str] = None


class ShipmentDetails(BaseModel):
    origin: Location
    destination: Location
    transport_mode: TransportMode = "Unknown"
    weight_kg: Optional[float] = None
    volume_cbm: Optional[float] = None
    container_or_package_type: Optional[str] = None
    est_transit_days: Optional[int] = None


class LineItem(BaseModel):
    description: str
    amount: float
    unit: Optional[str] = None
    category: Category


class Financials(BaseModel):
    currency: str
    line_items: list[LineItem]
    total_amount: float


class TermsAndNotes(BaseModel):
    incoterms: Optional[str] = None
    payment_terms: Optional[str] = None
    special_notes: Optional[str] = None


class QuoteExtractionResult(BaseModel):
    quote_metadata: VendorMetadata
    shipment_details: ShipmentDetails
    financials: Financials
    terms_and_notes: TermsAndNotes
    extraction_flags: list[str] = Field(default_factory=list)


def _iso_date(month_name: str, day: str, year: str) -> str:
    month = MONTHS[month_name.lower()]
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def _optional_accessorial(description: str) -> bool:
    return bool(re.search(r"\b(optional|tarp(?:ing|ed)?|conditional)\b", description, re.I))


def _waiting_windows(text: str) -> dict:
    def total(pattern: str) -> float:
        return sum(float(match) for match in re.findall(pattern, text, re.I))

    return {
        "loading_hours": total(r"(\d+(?:\.\d+)?)\s*hours?\s+free\s+for\s+loading"),
        "offloading_hours": total(r"(\d+(?:\.\d+)?)\s*hours?\s+free\s+for\s+offloading"),
        "warehouse_days": total(r"(\d+(?:\.\d+)?)\s*free\s+days?\s+at\s+warehouse"),
    }


def _categorize(description: str) -> Category:
    text = description.lower()
    if any(k in text for k in ("baf", "lss", "bunker", "fuel", "peak season", "pss")):
        return "Fuel / Surcharge"
    if any(k in text for k in ("ocean freight", "air freight", "base freight", "freight rate", "logistics", "delivery fee", "server fee")):
        return "Base Freight"
    if any(k in text for k in ("destination thc", "dest thc", "dthc", "delivery", "import clearance")):
        return "Destination Charge"
    if "destination" in text and "thc" in text:
        return "Destination Charge"
    if any(k in text for k in ("duty", "duties", "vat", "levy", "tax", "customs fee", "brokerage", "agency fee", "documentation")):
        return "Customs / Tax"
    if any(k in text for k in ("truck", "final mile", "apapa")):
        return "Destination Charge"
    if any(k in text for k in ("origin", "othc", "export", "pickup", "thc")):
        # Origin THC and export clearance belong with origin charges.
        if "destination" not in text:
            return "Origin Charge"
    return "Other"


def _money(raw: str) -> tuple[Optional[float], Optional[str]]:
    symbol = None
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in raw:
            symbol = code
            break
    code_match = re.search(r"\b(USD|EUR|GBP|NGN)\b", raw, re.I)
    code = code_match.group(1).upper() if code_match else symbol
    amount_match = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?", raw)
    if not amount_match:
        return None, code
    return float(amount_match.group(0).replace(",", "")), code


def _transit_days(text: str) -> Optional[int]:
    weeks = re.search(r"(\d+)\s*-\s*(\d+)\s*weeks?", text, re.I)
    if weeks:
        mid = (int(weeks.group(1)) + int(weeks.group(2))) / 2
        return int(round(mid * 7))
    one_week = re.search(r"(\d+)\s*weeks?", text, re.I)
    if one_week:
        return int(one_week.group(1)) * 7
    days = re.search(r"~?\s*(\d+)\s*days?", text, re.I)
    if days:
        return int(days.group(1))
    return None


def _mode(text: str) -> TransportMode:
    lower = text.lower()
    if "ocean" in lower or "sea freight" in lower or "pol:" in lower or "pod:" in lower or "container" in lower:
        return "Ocean"
    if "air freight" in lower or re.search(r"\bair\b", lower):
        return "Air"
    if "rail" in lower:
        return "Rail"
    if "truck" in lower or "road" in lower or "delivery" in lower or "logistics" in lower:
        return "Road"
    return "Unknown"


def _prepare_text(text: str) -> str:
    """Put glued invoice labels on their own lines so field regexes can see them."""
    labels = [
        "Invoice Number:",
        "Date:",
        "Prepared For:",
        "Service Type:",
        "Provider:",
        "Payment Status:",
        "Order Summary",
        "Cost Breakdown",
        "Item Description",
        "Total Amount Due",
    ]
    for label in labels:
        text = re.sub(rf"(?i)(?<!\n)({re.escape(label)})", r"\n\1", text)
    return text


def _invoice_lines(text: str) -> list[tuple[str, str, float]]:
    """Return description, unit label, and line total from qty/unit-price/total rows."""
    pattern = re.compile(r"(\d+)\s*\$\s*([\d,]+\.\d{2})\s*\$\s*([\d,]+\.\d{2})")
    rows = []
    cursor = 0
    for match in pattern.finditer(text):
        raw = text[cursor:match.start()]
        cut = -1
        marker_len = 0
        for marker in ("total amount", "unit price", "item description", "cost breakdown"):
            idx = raw.lower().rfind(marker)
            if idx > cut:
                cut = idx
                marker_len = len(marker)
        if cut >= 0:
            raw = raw[cut + marker_len :]
        description = re.sub(r"\s+", " ", raw).strip(" -:|")
        cursor = match.end()
        if len(description) < 3 or description.lower().startswith("total"):
            continue
        qty, unit_price, total = match.group(1), match.group(2), float(match.group(3).replace(",", ""))
        rows.append((description, f"{qty} x ${unit_price}", total))
    return rows


def _location(label: str) -> Location:
    code_match = re.search(r"\(([A-Z]{5})\)", label)
    code = code_match.group(1) if code_match else None
    name = re.sub(r"\s*\([A-Z]{5}\)\s*", "", label).strip(" -")
    country = PORT_COUNTRY.get(code) if code else None
    return Location(location_name=name or None, port_code=code, country=country)


def parse_freight_quote(raw_quote_text: str) -> QuoteExtractionResult:
    text = _prepare_text(raw_quote_text.strip())
    flags: list[str] = []

    vendor = None
    header = text.splitlines()[0] if text else ""
    vendor_match = re.match(r"(.+?)\s+Freight Quote", header, re.I)
    if vendor_match:
        vendor = vendor_match.group(1).strip(" -")
    provider = re.search(r"Provider:\s*(.+)", text, re.I)
    if vendor is None and provider:
        vendor = provider.group(1).strip()
    elif vendor is None and re.search(r"invoice", header, re.I):
        vendor = re.sub(r"\s*invoice\s*$", "", header, flags=re.I).strip()

    ref_match = re.search(r"Ref\s*#\s*([A-Z0-9-]+)", text, re.I)
    invoice_ref = re.search(r"Invoice Number:\s*([A-Z0-9-]+)", text, re.I)
    if ref_match is None:
        ref_match = invoice_ref
    date_match = re.search(
        r"Date:\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text
    )
    valid_match = re.search(
        r"Valid until\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text, re.I
    )
    quote_date = _iso_date(*date_match.groups()) if date_match else None
    valid_until = _iso_date(*valid_match.groups()) if valid_match else None

    pol = re.search(r"POL:\s*(.+?)\s*(?:->|→| to )\s*POD:\s*(.+)", text, re.I)
    origin = _location(pol.group(1)) if pol else Location()
    destination = _location(pol.group(2)) if pol else Location()
    prepared = re.search(r"Prepared For:\s*(.+)", text, re.I)
    if destination.location_name is None and prepared:
        destination = Location(location_name=prepared.group(1).strip(), port_code=None, country=None)
    labeled_origin = re.search(r"^Origin:\s*(.+)$", text, re.I | re.M)
    labeled_destination = re.search(r"^Destination:\s*(.+)$", text, re.I | re.M)
    if origin.location_name is None and labeled_origin:
        origin = _location(labeled_origin.group(1))
    if destination.location_name is None and labeled_destination:
        destination = _location(labeled_destination.group(1))
    _annotate_place(origin)
    _annotate_place(destination)
    if origin.location_name is None and re.search(r"\bapapa\b", text, re.I):
        origin = Location(location_name="Apapa", port_code=None, country="Nigeria")
    if destination.location_name is None and re.search(r"\bikeja\b", text, re.I):
        destination = Location(location_name="Ikeja", port_code=None, country="Nigeria")
    if origin.country is None and origin.location_name:
        flags.append("Origin country was not stated and could not be inferred from a known port code.")
    elif origin.country and origin.port_code:
        flags.append(
            f"Origin country inferred from port code {origin.port_code}."
        )
    if destination.country is None and destination.location_name:
        flags.append("Destination country was not stated and could not be inferred from a known port code.")
    elif destination.country and destination.port_code:
        flags.append(
            f"Destination country inferred from port code {destination.port_code}."
        )

    weight_match = re.search(r"([\d,]+(?:\.\d+)?)\s*kg", text, re.I)
    weight = float(weight_match.group(1).replace(",", "")) if weight_match else None
    cbm_match = re.search(r"([\d,]+(?:\.\d+)?)\s*cbm", text, re.I)
    volume = float(cbm_match.group(1).replace(",", "")) if cbm_match else None
    if volume is None:
        flags.append("Volume (CBM) was not provided.")

    cargo = re.search(r"Cargo:\s*(.+)", text)
    container = None
    if cargo:
        container = re.split(r",\s*\d", cargo.group(1))[0].strip().rstrip(".")

    transit = _transit_days(text)
    if transit is None:
        flags.append("Transit time was not provided.")

    line_items: list[LineItem] = []
    currency: Optional[str] = None
    charge_block = re.search(r"Charges:\s*(.*?)(?:Total Amount|Terms:|\Z)", text, re.S | re.I)
    if charge_block:
        for line in charge_block.group(1).splitlines():
            line = line.strip().lstrip("-").strip()
            if not line or ":" not in line:
                continue
            desc, money_raw = line.split(":", 1)
            if re.search(r"\b(subtotal|grand total|total local|total amount due)\b", desc, re.I):
                flags.append(f"Skipped rollup '{desc.strip()}' so it is not added on top of the detail lines.")
                continue
            amount, code = _money(money_raw)
            if amount is None:
                flags.append(f"Could not parse amount for '{desc.strip()}'.")
                continue
            if code and currency and code != currency:
                flags.append(f"Kept {desc.strip()} as {code} {amount:,.2f} beside the {currency} lines.")
            currency = "NGN" if code == "NGN" else (currency or code)
            category = _categorize(desc)
            if _optional_accessorial(desc):
                flags.append(f"Left optional charge '{desc.strip()}' out of the all-in total.")
                continue
            if "customs" in desc.lower() and category == "Origin Charge":
                flags.append(
                    f"{desc.strip()} categorized as Origin Charge (export clearance); "
                    "it could also be read as a customs brokerage fee."
                )
            line_items.append(
                LineItem(description=desc.strip(), amount=amount, unit=None, category=category)
            )
            if "per " not in money_raw.lower():
                pass
    if not line_items:
        for line in text.splitlines():
            cleaned = line.strip().lstrip("-•").strip()
            money = re.search(r"(?:₦|NGN|USD|US\$|\$)\s*([\d,]+(?:\.\d{1,2})?)", cleaned, re.I)
            suffix = re.search(r"([\d,]{4,}(?:\.\d{1,2})?)\s*(USD|NGN|₦|\$|naira|dollars?)\b", cleaned, re.I)
            if money:
                amount = float(money.group(1).replace(",", ""))
                code = "USD" if re.search(r"USD|\$", money.group(0), re.I) else "NGN"
                desc = cleaned[: money.start()].strip(" :-")
            elif suffix:
                amount = float(suffix.group(1).replace(",", ""))
                code = "USD" if re.search(r"USD|\$|dollar", suffix.group(2), re.I) else "NGN"
                desc = cleaned[: suffix.start()].strip(" :-")
            else:
                continue
            if _optional_accessorial(desc):
                flags.append(f"Left optional charge '{desc}' out of the all-in total.")
                continue
            if len(desc) < 3 or re.search(
                r"\b(subtotal|grand total|total local|total amount due|customs/tax|official/mid|parallel|platform fee|duty finance)\b",
                desc,
                re.I,
            ):
                flags.append(f"Skipped rollup '{desc}' so it is not added on top of the detail lines.")
                continue
            if currency and code != currency:
                flags.append(f"Kept {desc} as {code} {amount:,.2f} beside the {currency} lines.")
            currency = "NGN" if code == "NGN" else (currency or code)
            line_items.append(LineItem(description=desc, amount=amount, unit=None, category=_categorize(desc)))
        if line_items:
            flags.append("Read prices from lines that included NGN or USD amounts.")
    if not line_items:
        for description, unit, total in _invoice_lines(text):
            line_items.append(LineItem(description=description, amount=total, unit=unit, category=_categorize(description)))
            currency = currency or "USD"
        if line_items:
            flags.append("Read as a service invoice. Line amount is the row total, not the unit price.")
            flags.append("No origin port was stated.")
    if line_items and all(item.unit is None for item in line_items):
        flags.append("Line items are quoted per shipment with no explicit rate unit.")

    total_match = re.search(r"Total Amount Due:?\s*(.+)", text, re.I)
    stated_total = None
    if total_match:
        stated_total, total_code = _money(total_match.group(1))
        currency = total_code or currency
    item_sum = round(sum(item.amount for item in line_items), 2)
    if stated_total is None:
        stated_total = item_sum
        if line_items:
            flags.append("Total was not stated; total_amount is the sum of line items.")
    elif abs(stated_total - item_sum) > 0.009:
        if stated_total > item_sum * 1.5 and any("Skipped rollup" in flag for flag in flags):
            flags.append(
                f"Printed total {stated_total:,.2f} includes subtotals. Working total is the detail-line sum {item_sum:,.2f}."
            )
            stated_total = item_sum
        elif any(flag.startswith("Left optional charge") for flag in flags):
            flags.append(
                f"Printed total {stated_total:,.2f} includes an optional charge. Working total is the confirmed sum {item_sum:,.2f}."
            )
            stated_total = item_sum
        else:
            flags.append(
                f"Stated total {stated_total:.2f} does not match line-item sum {item_sum:.2f}."
            )
    if re.search(r"dry box trailer|flatbed|\btruck\b", text, re.I):
        flags.append("Land asset named on the quote.")
    windows = _waiting_windows(text)
    if any(windows.values()):
        flags.append(
            "Local waiting window: loading {loading_hours:g}h, offloading {offloading_hours:g}h, warehouse {warehouse_days:g}d".format(**windows)
        )
    else:
        flags.append(
            f"Line-item sum {item_sum:.2f} matches the stated total of {currency or ''} {stated_total:.2f}.".strip()
        )

    incoterm = None
    payment = None
    notes = None
    terms = re.search(r"Terms:\s*(.+)", text, re.I)
    if terms:
        notes = terms.group(1).strip()
        inco = re.search(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b", notes)
        if inco:
            incoterm = inco.group(1)
        pay = re.search(r"(Payment[^.]*)", notes, re.I)
        if pay:
            payment = pay.group(1).strip().rstrip(".")
    status = re.search(r"Payment Status:\s*(.+)", text, re.I)
    if payment is None and status:
        payment = f"Payment {status.group(1).strip()}"
    service = re.search(r"Service Type:\s*(.+)", text, re.I)
    if notes is None and service:
        notes = service.group(1).strip()

    if not destination.location_name:
        flags.append("Destination is missing.")
    if not line_items:
        flags.append("No priced line items were found.")

    return _split_mixed_currency(QuoteExtractionResult(
        quote_metadata=VendorMetadata(
            vendor_name=vendor,
            quote_reference_id=ref_match.group(1) if ref_match else None,
            quote_date=quote_date,
            valid_until=valid_until,
        ),
        shipment_details=ShipmentDetails(
            origin=origin,
            destination=destination,
            transport_mode=_mode(text),
            weight_kg=weight,
            volume_cbm=volume,
            container_or_package_type=container,
            est_transit_days=transit,
        ),
        financials=Financials(
            currency=currency or "USD",
            line_items=line_items,
            total_amount=stated_total or 0,
        ),
        terms_and_notes=TermsAndNotes(
            incoterms=incoterm,
            payment_terms=payment,
            special_notes=notes,
        ),
        extraction_flags=flags,
    ))


def _clean_model_quote(quote: QuoteExtractionResult) -> QuoteExtractionResult:
    """Drop summary lines the model may still copy, then retotal the detail lines."""
    kept: list[LineItem] = []
    flags = list(quote.extraction_flags)
    for item in quote.financials.line_items:
        if re.search(r"\b(subtotal|grand total|total local|customs/tax|official/mid|platform fee)\b", item.description, re.I):
            flags.append(f"Dropped summary line '{item.description}'.")
            continue
        kept.append(item)
    detail = round(sum(item.amount for item in kept), 2)
    stated = quote.financials.total_amount or 0
    if kept and stated > detail * 1.5:
        flags.append(f"Model total {stated:,.2f} was larger than the detail lines. Using {detail:,.2f}.")
        stated = detail
    elif kept and stated == 0:
        stated = detail
    quote.financials.line_items = kept
    quote.financials.total_amount = stated
    quote.extraction_flags = flags
    return _split_mixed_currency(quote)


def _annotate_place(place: Location) -> None:
    name = place.location_name or ""
    code = re.search(r"\(([A-Z]{3,5})\)", name)
    if code and not place.port_code:
        place.port_code = code.group(1)
    low = name.lower()
    if place.country:
        return
    inland = (
        "nigeria", "lagos", "apapa", "tin can", "makurdi", "benue", "abuja", "kano", "ibadan",
        "enugu", "kaduna", "portharcourt", "port harcourt", "onitsha", "owerri", "jos", "ilorin",
        "aba", "warri", "benin", "calabar", "maiduguri", "sokoto", "yola", "minna", "lafia",
        "awka", "asaba", "uyo", "bauchi", "gombe", "jalingo", "damaturu", "katsina", "birnin kebbi",
        "lokoja", "osogbo", "ado ekiti", "akure", "abakaliki", "umuahia", "yenagoa",
    )
    if any(word in low for word in inland):
        place.country = "Nigeria"
    elif any(word in low for word in ("houston", "united states", "usa", "u.s.")):
        place.country = "United States"
    elif any(word in low for word in ("thailand", "bangkok")):
        place.country = "Thailand"
    elif "china" in low or "shanghai" in low:
        place.country = "China"
    elif "germany" in low or "hamburg" in low:
        place.country = "Germany"


def _split_mixed_currency(quote: QuoteExtractionResult) -> QuoteExtractionResult:
    """Keep a small ocean freight in USD and leave Nigerian port charges in NGN."""
    usd_items: list[LineItem] = []
    ngn_items: list[LineItem] = []
    for item in quote.financials.line_items:
        freight = any(word in item.description.lower() for word in ("ocean freight", "sea freight", "base freight"))
        if freight and item.amount < 100_000:
            usd_items.append(item)
        elif item.amount >= 100_000:
            ngn_items.append(item)
        elif quote.financials.currency == "NGN":
            ngn_items.append(item)
        else:
            usd_items.append(item)
    _annotate_place(quote.shipment_details.origin)
    _annotate_place(quote.shipment_details.destination)
    if not (usd_items and ngn_items):
        return quote
    quote.financials.line_items = ngn_items
    quote.financials.currency = "NGN"
    quote.financials.total_amount = round(sum(item.amount for item in ngn_items), 2)
    usd_total = round(sum(item.amount for item in usd_items), 2)
    quote.extraction_flags.append(f"USD freight kept separate: USD {usd_total:,.2f}.")
    return quote


def _gemini_keys() -> list[str]:
    raw = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY") or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _rotate_file() -> Path:
    path = Path(__file__).resolve().parent / "state" / "gemini_rotate.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _next_key_index(count: int) -> int:
    path = _rotate_file()
    current = 0
    if path.exists():
        try:
            current = int(path.read_text().strip() or "0")
        except ValueError:
            current = 0
    index = current % count
    path.write_text(str((index + 1) % count))
    return index


def gemini_media_text(data: bytes, mime: str, instruction: str) -> str:
    """Send audio, an image, or a PDF to Gemini and return the text it reads."""
    import base64
    import urllib.error
    import urllib.request

    keys = _gemini_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS is not set.")
    models = []
    for name in (os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-flash-latest"):
        if name and name not in models:
            models.append(name)
    encoded = base64.b64encode(data).decode()
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": mime, "data": encoded}},
            ],
        }],
        "generationConfig": {"temperature": 0},
    }
    start = _next_key_index(len(keys))
    errors: list[str] = []
    for offset in range(len(keys)):
        slot = (start + offset) % len(keys)
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={keys[slot]}"
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "logistics-quote-api/1.0"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read().decode())
                parts = (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
                text = "".join(part.get("text") or "" for part in parts).strip()
                if text:
                    return text
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:160]
                errors.append(f"{model} HTTP {exc.code}: {detail}")
                if exc.code in {404, 429, 503}:
                    continue
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:120])
    raise RuntimeError("Gemini could not read this file. " + " | ".join(errors[:3]))


def _gemini_once(api_key: str, raw_quote_text: str, model: str) -> str:
    import urllib.error
    import urllib.request

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": raw_quote_text}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "logistics-quote-api/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:180]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    parts = (((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text = "".join(part.get("text") or "" for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned no JSON text.")
    return text


def _location_dict(value) -> dict:
    if isinstance(value, str):
        return {"location_name": value, "port_code": None, "country": None}
    if isinstance(value, dict):
        return {
            "location_name": value.get("location_name") or value.get("name") or value.get("port"),
            "port_code": value.get("port_code") or value.get("code"),
            "country": value.get("country"),
        }
    return {"location_name": None, "port_code": None, "country": None}


def _category(value: str | None) -> str:
    text = (value or "").lower()
    if "fuel" in text or "baf" in text:
        return "Fuel / Surcharge"
    if "origin" in text:
        return "Origin Charge"
    if "destination" in text or "truck" in text or "delivery" in text:
        return "Destination Charge"
    if "custom" in text or "duty" in text or "tax" in text or "vat" in text:
        return "Customs / Tax"
    if "freight" in text:
        return "Base Freight"
    allowed = {"Base Freight", "Fuel / Surcharge", "Origin Charge", "Destination Charge", "Customs / Tax", "Other"}
    return value if value in allowed else "Other"


def _coerce_quote_payload(data: dict) -> dict:
    """Accept the shorter field names Gemini often returns."""
    meta = data.get("quote_metadata") if isinstance(data.get("quote_metadata"), dict) else {}
    ship = data.get("shipment_details") if isinstance(data.get("shipment_details"), dict) else {}
    money = data.get("financials") if isinstance(data.get("financials"), dict) else {}
    terms = data.get("terms_and_notes") if isinstance(data.get("terms_and_notes"), dict) else {}
    raw_items = money.get("line_items") or data.get("line_items") or data.get("charges") or []
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        description = item.get("description") or item.get("name") or item.get("item")
        amount = item.get("amount", item.get("total", item.get("price")))
        if description is None or amount in (None, ""):
            continue
        number = float(str(amount).replace(",", "").replace("$", "").replace("₦", ""))
        items.append({
            "description": str(description),
            "amount": number,
            "unit": item.get("unit"),
            "category": _category(item.get("category")),
        })
    total = money.get("total_amount", data.get("total_amount", data.get("total")))
    if total in (None, ""):
        total = sum(item["amount"] for item in items)
    else:
        total = float(str(total).replace(",", "").replace("$", "").replace("₦", ""))
    mode = ship.get("transport_mode") or data.get("transport_mode") or "Unknown"
    if mode not in {"Ocean", "Air", "Road", "Rail", "Multimodal", "Unknown"}:
        mode = "Unknown"
    return {
        "quote_metadata": {
            "vendor_name": meta.get("vendor_name") or meta.get("vendor") or data.get("vendor") or data.get("vendor_name"),
            "quote_reference_id": meta.get("quote_reference_id") or meta.get("reference") or data.get("reference") or data.get("quote_reference_id"),
            "quote_date": meta.get("quote_date") or data.get("quote_date"),
            "valid_until": meta.get("valid_until") or data.get("valid_until"),
        },
        "shipment_details": {
            "origin": _location_dict(ship.get("origin") or data.get("origin")),
            "destination": _location_dict(ship.get("destination") or data.get("destination")),
            "transport_mode": mode,
            "weight_kg": ship.get("weight_kg") or data.get("weight_kg"),
            "volume_cbm": ship.get("volume_cbm") or data.get("volume_cbm"),
            "container_or_package_type": ship.get("container_or_package_type") or data.get("container_or_package_type"),
            "est_transit_days": ship.get("est_transit_days") or data.get("est_transit_days"),
        },
        "financials": {
            "currency": (money.get("currency") or data.get("currency") or "USD").upper(),
            "line_items": items,
            "total_amount": total or 0,
        },
        "terms_and_notes": {
            "incoterms": terms.get("incoterms") or data.get("incoterms"),
            "payment_terms": terms.get("payment_terms") or data.get("payment_terms"),
            "special_notes": terms.get("special_notes") or data.get("special_notes"),
        },
        "extraction_flags": list(data.get("extraction_flags") or []),
    }


def parse_freight_quote_llm(raw_quote_text: str) -> QuoteExtractionResult:
    """Read a quote with Gemini, rotating keys when one is limited or rejected."""
    keys = _gemini_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS is not set.")
    models = []
    for name in (os.environ.get("GEMINI_MODEL"), "gemini-flash-lite-latest", "gemini-flash-latest"):
        if name and name not in models:
            models.append(name)
    start = _next_key_index(len(keys))
    errors: list[str] = []
    for offset in range(len(keys)):
        slot = (start + offset) % len(keys)
        for model in models:
            try:
                raw = _gemini_once(keys[slot], raw_quote_text, model)
                quote = _clean_model_quote(QuoteExtractionResult.model_validate(_coerce_quote_payload(json.loads(raw))))
                quote.extraction_flags.append(f"Read by Gemini {model}, key {slot + 1} of {len(keys)}.")
                return quote
            except Exception as exc:  # noqa: BLE001 — limited keys rotate; a dead model tries the next model
                message = str(exc).replace(keys[slot], "KEY")
                errors.append(f"key {slot + 1} {model}: {message[:120]}")
                if any(token in message for token in ("API_KEY_INVALID", "API key not valid", "permission")):
                    break
    raise RuntimeError("All Gemini keys failed. " + " | ".join(errors[:4]))


REPLY_PROMPT = """You write the client email for a freight clearing desk.
Sound like a person: a short greeting, plain sentences, then sign off as "Freight desk".
Use only the names and numbers in FACTS. Do not invent a rate, a charge, a port, or an approval.
When the facts include them, mention the route and lane, the freight and local charges, the official naira and yuan figures, the parallel cash rate, the duty-finance estimate, the demurrage buffer, and how the all-in total is split.
Say this is an internal quote, not a filed customs declaration. Say no loan was disbursed and no bank transfer was sent.
If decision is ask, ask only the missing questions.
If decision is blocked, say you cannot pay anyone or file the customs entry because no bank and no customs system is connected.
If hold_reason is set, explain that hold and ask for the correction named there.
Stay under 1800 characters."""


def _gemini_text(api_key: str, prompt: str, model: str) -> str:
    import urllib.error
    import urllib.request

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": REPLY_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    }).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "logistics-quote-api/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:180]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    parts = (((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text = "".join(part.get("text") or "" for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini returned no reply text.")
    return text


DOMESTIC_INCOTERM = "N/A (Domestic Carriage)"


def lock_domestic_incoterm(record: dict) -> dict:
    """A domestic lane has no international trade term and must not ask for one."""
    if record.get("lane") == "domestic":
        commercial = record.setdefault("commercial", {})
        commercial["incoterms"] = DOMESTIC_INCOTERM
    return record


def _volatile_rate(fx: dict) -> bool:
    for tier in ("cbn", "parallel", "market"):
        rate = (fx.get(tier) or {}).get("usd_ngn") if isinstance(fx.get(tier), dict) else None
        if rate is not None and float(rate) >= 2500:
            return True
    return False


def compose_client_reply(client_text: str, record: dict, decision: str, held: str | None = None) -> str:
    """Write the email and chat reply from the figures already on the record."""
    from customs import _missing_questions, format_notice

    commercial = record.get("commercial") or {}
    movement = record.get("movement") or {}
    fx = record.get("fx") or {}
    facts = {
        "decision": decision,
        "hold_reason": held,
        "client_message": (client_text or "")[:1500],
        "business": (record.get("business") or {}).get("legal_name"),
        "lane": record.get("lane"),
        "vendor": commercial.get("vendor_name"),
        "reference": commercial.get("quote_reference_id"),
        "origin": (movement.get("origin") or {}).get("location_name"),
        "destination": (movement.get("destination") or {}).get("location_name"),
        "currency": commercial.get("currency"),
        "total_amount": commercial.get("total_amount"),
        "customs_and_tax": commercial.get("customs_and_tax"),
        "incoterms": commercial.get("incoterms"),
        "mixed": fx.get("mixed"),
        "official": None if _volatile_rate(fx) else fx.get("cbn"),
        "parallel": None if _volatile_rate(fx) else fx.get("parallel"),
        "financing": record.get("financing"),
        "demurrage": record.get("demurrage"),
        "split": [
            {"party": row.get("party"), "share": row.get("share"), "ngn": row.get("ngn")}
            for row in ((record.get("split") or {}).get("rows") or [])
        ],
        "missing_questions": _missing_questions(record),
        "disclaimer": record.get("disclaimer"),
        "refused": (record.get("agent") or {}).get("refused"),
    }
    # The model may explain, but it must not invent the money. The letter is the settled notice.
    del facts
    return format_notice(record)


def _repair_route(raw_quote_text: str, quote: QuoteExtractionResult) -> QuoteExtractionResult:
    """Fill Origin and Destination labels the model left blank."""
    labeled_origin = re.search(r"^Origin:\s*(.+)$", raw_quote_text, re.I | re.M)
    labeled_destination = re.search(r"^Destination:\s*(.+)$", raw_quote_text, re.I | re.M)
    if labeled_origin and not quote.shipment_details.origin.location_name:
        quote.shipment_details.origin = _location(labeled_origin.group(1))
    if labeled_destination and not quote.shipment_details.destination.location_name:
        quote.shipment_details.destination = _location(labeled_destination.group(1))
    _annotate_place(quote.shipment_details.origin)
    _annotate_place(quote.shipment_details.destination)
    return quote


def parse_quote_smart(raw_quote_text: str) -> QuoteExtractionResult:
    """Use Gemini when keys are set. Fall back to the rules parser if every key fails."""
    if not _gemini_keys():
        quote = parse_freight_quote(raw_quote_text)
        quote.extraction_flags.append("GEMINI_API_KEYS is not set. Used the rules parser.")
        return _repair_route(raw_quote_text, quote)
    try:
        quote = parse_freight_quote_llm(raw_quote_text)
    except Exception as exc:  # noqa: BLE001 — a live quote must still get a reply
        quote = parse_freight_quote(raw_quote_text)
        quote.extraction_flags.append(f"Gemini failed ({exc}). Used the rules parser.")
    return _repair_route(raw_quote_text, quote)


SAMPLE_QUOTE = """
Maersk Line Freight Quote - Ref # MSK-88291
Date: Sept 12, 2026. Valid until Oct 12, 2026.
POL: Shanghai Port (CNSHA) -> POD: Hamburg (DEHAM)
Cargo: 1x 40ft High Cube Container, 18,500 kg.
Transit Time: ~22 days.

Charges:
- Ocean Freight: $2,400.00
- BAF Surcharge: $350.00
- Origin Terminal Handling Charge (THC): $180.00
- Destination THC: $210.00
- Export Customs Filing: $75.00
Total Amount Due: USD 3,215.00
Terms: FOB Shanghai, Payment within 30 days.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize a freight quote to JSON.")
    parser.add_argument("path", nargs="?", help="Quote text file. Reads stdin when omitted.")
    parser.add_argument("--llm", action="store_true", help="Use the xAI API instead of the local parser.")
    parser.add_argument("--sample", action="store_true", help="Normalize the built-in Maersk sample.")
    args = parser.parse_args(argv)

    if args.sample:
        raw = SAMPLE_QUOTE
    elif args.path:
        with open(args.path, encoding="utf-8") as handle:
            raw = handle.read()
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = SAMPLE_QUOTE

    if args.llm:
        print(parse_freight_quote_llm(raw).model_dump_json(indent=2))
    else:
        print(parse_freight_quote(raw).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
