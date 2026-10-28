"""Quote desk layer: official FX, a user-set parallel rate, duty-finance estimate, demurrage buffer, and a payout split.

Official USD/NGN and USD/CNY come from the open ExchangeRate-API mid-market feed.
That feed is not the CBN customs assessment rate. A saved CBN rate overrides it.
The parallel rate is whatever the business types in. Nothing here books a loan or sends money.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RATE_CACHE = ROOT / "state" / "fx_rates.json"
OPEN_FX = "https://open.er-api.com/v6/latest/USD"

DEFAULTS = {
    "cbn_usd_ngn": None,
    "parallel_usd_ngn": None,
    "finance_fee_rate": 0.02,
    "demurrage_buffer_ngn": 350_000,
    "demurrage_days": 7,
    "fallback_official_usd_ngn": None,
    "fallback_parallel_usd_ngn": None,
    "split": {
        "shipping_line": 0.70,
        "trucker": 0.15,
        "clearing_agent": 0.12,
        "platform_fee": 0.03,
    },
}


def _env_rate(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_fx_settings(business: dict | None = None) -> dict:
    saved = {}
    if RATE_CACHE.exists():
        saved = json.loads(RATE_CACHE.read_text(encoding="utf-8"))
    settings = {**DEFAULTS, **saved}
    if not settings.get("fallback_official_usd_ngn"):
        settings["fallback_official_usd_ngn"] = _env_rate("FX_FALLBACK_OFFICIAL_USD_NGN", 1550)
    if not settings.get("fallback_parallel_usd_ngn"):
        settings["fallback_parallel_usd_ngn"] = _env_rate("FX_FALLBACK_PARALLEL_USD_NGN", 1650)
    if business:
        for key in ("cbn_usd_ngn", "parallel_usd_ngn", "finance_fee_rate", "demurrage_buffer_ngn", "demurrage_days"):
            if business.get(key) not in (None, ""):
                settings[key] = business[key]
    return settings


def save_fx_settings(updates: dict) -> dict:
    current = load_fx_settings()
    for key in ("cbn_usd_ngn", "parallel_usd_ngn", "finance_fee_rate", "demurrage_buffer_ngn", "demurrage_days", "fallback_official_usd_ngn", "fallback_parallel_usd_ngn"):
        if key in updates and updates[key] is not None:
            current[key] = updates[key]
    RATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RATE_CACHE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


_MARKET_CACHE: dict = {"at": 0.0, "data": None}


def fetch_market_rates() -> dict:
    now = time.time()
    if _MARKET_CACHE["data"] is not None and now - _MARKET_CACHE["at"] < 600:
        return _MARKET_CACHE["data"]
    from cache import get_json, set_json

    cached = get_json("fx:market")
    if isinstance(cached, dict) and cached.get("usd_ngn"):
        _MARKET_CACHE["at"] = now
        _MARKET_CACHE["data"] = cached
        return cached
    request = urllib.request.Request(OPEN_FX, headers={"User-Agent": "logistics-quote-api/1.0"})
    with urllib.request.urlopen(request, timeout=4) as response:
        payload = json.loads(response.read().decode())
    rates = payload.get("rates") or {}
    usd_ngn = float(rates["NGN"])
    cny_per_usd = float(rates["CNY"])
    result = {
        "source": "open.er-api.com mid-market",
        "as_of": payload.get("time_last_update_utc"),
        "usd_ngn": round(usd_ngn, 4),
        "usd_cny": round(cny_per_usd, 4),
        "cny_ngn": round(usd_ngn / cny_per_usd, 4),
        "rates": rates,
    }
    _MARKET_CACHE["at"] = now
    _MARKET_CACHE["data"] = result
    from cache import set_json

    set_json("fx:market", result, 600)
    return result


def _money(amount: float, rate: float | None) -> float | None:
    if rate is None:
        return None
    return round(amount * rate, 2)


def quote_views(amount: float, currency: str, settings: dict, market: dict | None) -> dict:
    """Express one quote total in USD, CNY, and NGN under two rate tiers."""
    currency = (currency or "USD").upper()
    market = market or {}
    usd_ngn_market = market.get("usd_ngn")
    usd_cny = market.get("usd_cny") or 7.2
    saved_cbn = settings.get("cbn_usd_ngn")
    cbn = saved_cbn if not _rate_out_of_band(saved_cbn) and saved_cbn else usd_ngn_market
    if _rate_out_of_band(cbn):
        cbn = None
    parallel = settings.get("parallel_usd_ngn")
    if _rate_out_of_band(parallel):
        parallel = None

    def to_usd(value: float) -> float | None:
        if currency == "USD":
            return value
        if currency == "NGN" and cbn:
            return value / cbn
        if currency == "CNY":
            return value / usd_cny
        rate = (market.get("rates") or {}).get(currency)
        return value / float(rate) if rate and float(rate) > 0 else None

    usd = to_usd(amount)
    def pack(ngn_per_usd: float | None) -> dict:
        ngn = round(amount, 2) if currency == "NGN" else _money(usd, ngn_per_usd) if usd is not None else None
        return {
            "USD": round(usd, 2) if usd is not None else None,
            "CNY": round(usd * usd_cny, 2) if usd is not None else None,
            "NGN": ngn,
            "usd_ngn": ngn_per_usd,
        }

    return {
        "source_currency": currency,
        "cbn": pack(cbn),
        "parallel": pack(float(parallel) if parallel else None),
        "market": market,
        "note": "CBN column uses a saved customs rate when set, otherwise the mid-market feed. Parallel uses only the rate you enter.",
    }


FX_PENDING = "Official FX Rate: [Market Rates Pending Verification]"


def _rate_out_of_band(rate: float | None) -> bool:
    return rate is not None and (float(rate) < 1000 or float(rate) > 2000)


def validate_displayed_fx(views: dict, market: dict | None, currency: str) -> dict:
    """Reject an official or parallel pair whose naira divided by dollars is outside 1,000–2,000."""
    market = market or {}
    mixed = bool(views.get("mixed"))
    violated = False
    for tier in ("cbn", "parallel"):
        block = dict(views.get(tier) or {})
        usd = block.get("USD")
        ngn = block.get("NGN")
        used = block.get("usd_ngn")
        implied = (ngn / usd) if usd and ngn and not mixed else None
        if not _rate_out_of_band(implied) and not _rate_out_of_band(used):
            if implied is not None:
                block["calculated_usd_ngn"] = round(implied, 4)
                views[tier] = block
            continue
        violated = True
        if (currency or "").upper() == "NGN":
            block["USD"] = block["CNY"] = block["usd_ngn"] = None
        else:
            block["NGN"] = block["CNY"] = block["usd_ngn"] = None
            if (currency or "").upper() != "USD":
                block["USD"] = None
        block["anomaly"] = True
        views[tier] = block
    official = dict(views.get("cbn") or {})
    if (currency or "").upper() != "NGN" and not official.get("usd_ngn"):
        official["NGN"] = official["CNY"] = official["usd_ngn"] = None
        official["anomaly"] = True
        views["cbn"] = official
        violated = True
    if violated:
        views["fx_anomaly"] = True
        views["error"] = FX_PENDING
        views["note"] = FX_PENDING
    return views


def financing_offer(customs_amount: float, currency: str, views: dict, settings: dict) -> dict:
    fee_rate = float(settings.get("finance_fee_rate") or 0.02)
    code = currency.upper()
    rate = views["cbn"].get("usd_ngn")
    usd_cny = (views.get("market") or {}).get("usd_cny") or 7.2
    principal = None
    if customs_amount and code == "NGN":
        principal = round(customs_amount, 2)
    elif customs_amount and rate and code == "USD":
        principal = round(customs_amount * rate, 2)
    elif customs_amount and rate and code == "CNY":
        principal = round(customs_amount / usd_cny * rate, 2)
    if not principal:
        return {
            "offered": False,
            "reason": "This quote has no customs or duty amount to finance.",
            "fee_rate": fee_rate,
        }
    fee = round(principal * fee_rate, 2)
    return {
        "offered": True,
        "principal_ngn": principal,
        "fee_rate": fee_rate,
        "origination_fee_ngn": fee,
        "repayable_ngn": round(principal + fee, 2),
        "status": "estimate",
        "reason": "Estimate only. No lender has approved or disbursed a clearing loan.",
    }


def _waiting_from_flags(record: dict) -> dict:
    loading = offloading = warehouse = 0.0
    for flag in record.get("extraction_flags") or []:
        match = re.search(
            r"Local waiting window: loading ([0-9.]+)h, offloading ([0-9.]+)h, warehouse ([0-9.]+)d",
            flag,
        )
        if match:
            loading += float(match.group(1))
            offloading += float(match.group(2))
            warehouse += float(match.group(3))
    return {"loading_hours": loading, "offloading_hours": offloading, "warehouse_days": warehouse}


def demurrage_guard(record: dict, settings: dict) -> dict:
    destination = ((record.get("movement") or {}).get("destination") or {}).get("location_name") or ""
    country = ((record.get("movement") or {}).get("destination") or {}).get("country") or ""
    watched = any(name in f"{destination} {country}".lower() for name in ("lagos", "apapa", "tin can", "tincan", "nigeria"))
    from api.store import PORT_BUFFERS, port_risk_level

    company_id = (record.get("business") or {}).get("id")
    level = port_risk_level(company_id)
    buffer_ngn = float(settings.get("demurrage_buffer_ngn") or PORT_BUFFERS.get(level, 350_000))
    ocean = watched or record.get("lane") == "import"
    windows = _waiting_from_flags(record)
    has_window = any(windows.values())
    window_hours = windows["loading_hours"] + windows["offloading_hours"] + windows["warehouse_days"] * 24
    if has_window:
        return {
            "applies": True,
            "port_watch": watched,
            "level": level,
            "free_days": windows["warehouse_days"] or int(settings.get("demurrage_days") or 7),
            "loading_hours": windows["loading_hours"],
            "offloading_hours": windows["offloading_hours"],
            "warehouse_days": windows["warehouse_days"],
            "buffer_hours": window_hours,
            "buffer_ngn": buffer_ngn if ocean else 0,
            "reason": (
                f"Demurrage buffer {window_hours:g} hours "
                f"({windows['loading_hours']:g} hours free for loading, "
                f"{windows['offloading_hours']:g} hours free for offloading, "
                f"{windows['warehouse_days']:g} free days at warehouse)."
            ),
        }
    return {
        "applies": ocean,
        "port_watch": watched,
        "level": level,
        "free_days": int(settings.get("demurrage_days") or 7),
        "buffer_ngn": buffer_ngn if ocean else 0,
        "reason": (
            f"Port risk on the desk is {level}. Buffer NGN {buffer_ngn:,.0f} if clearing passes the free days. "
            "This level is set by your desk, not a live Apapa feed."
            if ocean
            else "No local waiting window was written on this quote, so the demurrage buffer is 0."
        ),
    }


INLAND_SPLIT = {
    "trucker": 0.80,
    "platform_fee": 0.10,
    "security_and_permits": 0.10,
}


def split_plan(record: dict, views: dict, financing: dict, demurrage: dict, settings: dict) -> dict:
    inland = record.get("lane") == "domestic"
    weights = INLAND_SPLIT if inland else (settings.get("split") or DEFAULTS["split"])
    usd = views["cbn"]["USD"] or 0
    rate = views["cbn"]["usd_ngn"] or 0
    ngn_total = views["cbn"]["NGN"] or 0
    rows = []
    for name, weight in weights.items():
        rows.append({
            "party": name,
            "share": weight,
            "usd": round(usd * weight, 2),
            "ngn": round(ngn_total * weight, 2) if ngn_total else None,
            "currency_preference": "NGN" if inland or name != "shipping_line" else "USD",
            "role": "fleet_owner" if inland and name == "trucker" else name,
            "pays_when": {
                "shipping_line": "When the freight invoice is accepted",
                "trucker": "After delivery is confirmed. Covers diesel, vehicle overhead, and the driver.",
                "clearing_agent": "After the gate pass or transit permit is recorded",
                "security_and_permits": "When transit security and permits are confirmed",
                "platform_fee": "When the all-in quote is paid",
            }.get(name, "On payment"),
        })
    return {
        "rows": rows,
        "customs_duty_ngn": financing.get("principal_ngn") or 0,
        "demurrage_buffer_ngn": demurrage.get("buffer_ngn") or 0,
        "platform_fee_rate": weights.get("platform_fee"),
        "fx_spread_note": "A parallel-versus-official gap is shown for cash planning. The desk does not exchange currency.",
        "execution": "Calculated routing only. No transfer is sent to customs, a trucker, or a bank.",
        "usd_ngn_used": rate,
    }


def enrich(record: dict, business: dict | None = None) -> dict:
    settings = load_fx_settings(business)
    market = None
    try:
        market = fetch_market_rates()
    except Exception as exc:  # noqa: BLE001 — quote still returns if the rate host is down
        record.setdefault("extraction_flags", []).append(f"FX feed unavailable: {exc}")
        official_fallback = float(settings.get("fallback_official_usd_ngn") or 1550)
        market = {"source": "configured fallback", "usd_ngn": official_fallback, "usd_cny": 7.2, "cny_ngn": round(official_fallback / 7.2, 4)}
        record.setdefault("extraction_flags", []).append(
            f"Official NGN used fallback {official_fallback:,.0f} because the rate feed failed. This is not a CBN customs print."
        )
    commercial = record["commercial"]
    movement = record.get("movement") or {}
    named = bool(commercial.get("vendor_name") or commercial.get("quote_reference_id"))
    placed = bool((movement.get("origin") or {}).get("location_name") or (movement.get("destination") or {}).get("location_name"))
    priced = bool(record.get("line_items")) and float(commercial.get("total_amount") or 0) > 0
    record["agent_ready"] = priced and (named or placed)
    if not record["agent_ready"]:
        record.setdefault("extraction_flags", []).append(
            "No priced charge was found, so financing and the payout split were withheld."
            if not priced
            else "No vendor or route was found, so financing and the payout split were withheld."
        )
        record["fx"] = None
        record["financing"] = {"offered": False, "reason": "Withheld until the quote has a vendor or a route."}
        record["demurrage"] = {"buffer_ngn": 0, "reason": "Withheld until the quote has a route."}
        record["split"] = {"rows": [], "execution": "No split. The quote was not understood."}
        record["agent"] = {"decided": [], "refused": "Did not price, finance, or split an unidentified quote."}
        return record
    if commercial.get("currency") != "NGN" and not settings.get("parallel_usd_ngn"):
        parallel_fallback = float(settings.get("fallback_parallel_usd_ngn") or 1650)
        settings = {**settings, "parallel_usd_ngn": parallel_fallback}
        record.setdefault("extraction_flags", []).append(
            f"Parallel cash used fallback {parallel_fallback:,.0f}. Save your own rate to replace it."
        )
    views = quote_views(commercial["total_amount"], commercial["currency"], settings, market)
    totals = {}
    for item in record.get("line_items", []):
        code = item.get("currency") or commercial["currency"]
        totals[code] = totals.get(code, 0) + float(item.get("amount") or 0)
    if len(totals) > 1:
        record["currency_totals"] = {code: round(amount, 2) for code, amount in totals.items()}
        parts = [quote_views(amount, code, settings, market) for code, amount in totals.items()]
        for tier in ("cbn", "parallel"):
            for code in ("USD", "NGN", "CNY"):
                amounts = [part[tier][code] for part in parts]
                views[tier][code] = round(sum(amounts), 2) if all(value is not None for value in amounts) else None
        if set(totals) == {"USD", "NGN"}:
            views["mixed"] = {"usd_freight": totals["USD"], "local_ngn": totals["NGN"]}
    views = validate_displayed_fx(views, market, commercial.get("currency") or "")
    duty = commercial.get("customs_and_tax") or 0
    financing = financing_offer(duty, commercial["currency"], views, settings)
    guard = demurrage_guard(record, settings)
    record["fx"] = views
    from customs import fold_road_split, land_corridor

    if land_corridor(record):
        fold_road_split(record)
    record["financing"] = financing
    record["demurrage"] = guard
    record["split"] = split_plan(record, views, financing, guard, settings)
    record["agent"] = {
        "decided": [
            "Priced the quote in USD, CNY, and NGN",
            "Checked whether any duty amount can be financed",
            "Added a demurrage planning buffer when the move looks like a Nigeria import",
            "Split the all-in total across shipping line, trucker, clearing agent, and platform fee",
        ],
        "refused": "Did not book a loan, exchange cash, or pay customs.",
    }
    return record
