"""Estimated Nigerian customs charges from a commodity description.

The HS code and tariff come from a small desk table, or from an 8-digit code
already written in the message. This is not an Nigeria Customs Service assessment.
"""

from __future__ import annotations

import re

# keyword, hs, import duty rate, import adjustment tax rate, label
_TABLE = (
    ("solar inverter", "8504.40.00", 0.05, 0.0, "Static converters, including solar inverters"),
    ("solar", "8541.43.00", 0.0, 0.0, "Photovoltaic cells assembled in modules"),
    ("used car", "8703.23.19", 0.20, 0.0, "Used passenger motor vehicles"),
    ("used vehicle", "8703.23.19", 0.20, 0.0, "Used passenger motor vehicles"),
    ("vehicle", "8703.23.19", 0.20, 0.0, "Passenger motor vehicles"),
    ("chemical", "2915.21.00", 0.10, 0.0, "Acetic acid and similar chemicals"),
    ("rice", "1006.30.00", 0.10, 0.0, "Semi-milled or wholly milled rice"),
    ("generator", "8502.13.00", 0.05, 0.0, "Generating sets"),
    ("phone", "8517.13.00", 0.10, 0.0, "Smartphones"),
    ("textile", "6204.62.00", 0.20, 0.0, "Women's or girls' cotton trousers"),
)

ETLS = 0.005
CISS = 0.01
VAT = 0.075


def _cif_ngn(record: dict) -> float:
    fx = record.get("fx") or {}
    official = (fx.get("cbn") or {}).get("NGN")
    if official:
        return float(official)
    commercial = record.get("commercial") or {}
    if (commercial.get("currency") or "").upper() == "NGN":
        return float(commercial.get("total_amount") or 0)
    return 0.0


def _match(text: str) -> tuple[str, float, float, str] | None:
    found = re.search(r"\b(\d{4}\.\d{2}\.\d{2}|\d{8})\b", text)
    if found:
        raw = found.group(1)
        code = raw if "." in raw else f"{raw[:4]}.{raw[4:6]}.{raw[6:8]}"
        return code, 0.10, 0.0, "HS code written on the message. Duty rate assumed at 10% until a tariff book is connected."
    low = text.lower()
    for keyword, code, duty, iat, label in _TABLE:
        if keyword in low:
            return code, duty, iat, label
    return None


def estimate_duty(text: str, record: dict) -> dict | None:
    matched = _match(text or "")
    if not matched:
        return None
    code, duty_rate, iat_rate, label = matched
    cif = _cif_ngn(record)
    if cif <= 0:
        return {
            "hs_code": code,
            "label": label,
            "reason": "A commodity was recognised, but there is no naira value to assess yet.",
        }
    import_duty = round(cif * duty_rate, 2)
    iat = round(cif * iat_rate, 2)
    etls = round(cif * ETLS, 2)
    ciss = round(cif * CISS, 2)
    vat_base = cif + import_duty + iat + etls + ciss
    vat = round(vat_base * VAT, 2)
    total = round(import_duty + iat + etls + ciss + vat, 2)
    return {
        "hs_code": code,
        "label": label,
        "cif_ngn": cif,
        "import_duty_rate": duty_rate,
        "import_duty_ngn": import_duty,
        "iat_rate": iat_rate,
        "iat_ngn": iat,
        "etls_ngn": etls,
        "ciss_ngn": ciss,
        "vat_ngn": vat,
        "total_ngn": total,
        "basis": "Estimated on the official all-in naira figure, not a customs-assessed CIF.",
    }
