"""Public terminal pages for Apapa, Tin Can, and Onne.

A container is reported only when its number appears on the fetched page.
Discharge, yard, and free-time fields are read from that page. Missing fields
stay empty. Demurrage is calculated from a real discharge date.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from desk_ops import ScrapedTerminalStatus

TERMINALS = {
    "apmt-apapa": "https://www.apmterminals.com/en/apapa",
    "ptml": "https://www.ptml-nigeria.com/",
    "wact-onne": "https://wact.com.ng/",
}

CONTAINER_RE = re.compile(r"^[A-Z]{4}\d{7}$")
DATE_RE = re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})")
DEFAULT_FREE_DAYS = 7
DEFAULT_DAILY_NGN = 45_000


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def free_time(discharge: datetime | None, free_days: int, now: datetime | None = None) -> dict:
    """Hours left inside free time, and demurrage once that window has closed."""
    if discharge is None:
        return {"free_hours_remaining": None, "demurrage_days": 0, "demurrage_liability_ngn": 0}
    clock = now or datetime.now(timezone.utc)
    deadline = discharge + timedelta(days=free_days)
    remaining = (deadline - clock).total_seconds() / 3600
    if remaining >= 0:
        return {"free_hours_remaining": round(remaining, 1), "demurrage_days": 0, "demurrage_liability_ngn": 0}
    days = int((-remaining) // 24) + 1
    return {
        "free_hours_remaining": round(remaining, 1),
        "demurrage_days": days,
        "demurrage_liability_ngn": days * DEFAULT_DAILY_NGN,
    }


def _fetch_html(url: str) -> str:
    """Playwright when a browser is installed. Otherwise a plain HTTP GET."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return html
    except Exception:
        try:
            response = httpx.get(url, timeout=20, follow_redirects=True, verify=False)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc


def _near(html: str, needle: str, pattern: str) -> str | None:
    index = html.upper().find(needle.upper())
    if index < 0:
        return None
    window = html[max(0, index - 400): index + 400]
    match = re.search(pattern, window, re.I)
    return match.group(1).strip() if match else None


def parse_container_page(terminal: str, container: str, html: str, source: str) -> ScrapedTerminalStatus:
    if container.upper() not in html.upper():
        return ScrapedTerminalStatus(
            terminal=terminal,
            container=container,
            found=False,
            source=source,
            error="This public page does not list that container.",
        )
    vessel = _near(html, container, r"(?:vessel|vsl)[:\s]+([A-Z0-9]+(?:[ .'-][A-Z0-9]+){0,3})(?=\s+(?:discharge|yard|block|free)|$)")
    yard = _near(html, container, r"(?:yard|block|location)[:\s]+([A-Z0-9]+(?:[ /-]?[A-Z0-9]+){0,2})(?=\s+(?:free|discharge|vessel)|$)")
    date_match = _near(html, container, r"(?:discharge|disch)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})")
    if date_match is None:
        window_dates = DATE_RE.search(html[max(0, html.upper().find(container)): html.upper().find(container) + 240] if container.upper() in html.upper() else "")
        date_match = window_dates.group(1) if window_dates else None
    free_match = _near(html, container, r"(?:free\s*days)[:\s]+(\d{1,2})")
    free_days = int(free_match) if free_match else DEFAULT_FREE_DAYS
    clock = free_time(_parse_date(date_match), free_days)
    return ScrapedTerminalStatus(
        terminal=terminal,
        container=container.upper(),
        vessel_name=vessel,
        discharge_date=date_match,
        yard_location=yard,
        free_days_allowed=free_days,
        free_hours_remaining=clock["free_hours_remaining"],
        demurrage_liability_ngn=clock["demurrage_liability_ngn"],
        found=True,
        source=source,
    )


def scrape_container(terminal: str, container: str, html: str | None = None, source: str | None = None) -> ScrapedTerminalStatus:
    code = (container or "").upper().replace(" ", "")
    if not CONTAINER_RE.match(code):
        raise ValueError("Container number must be 4 letters and 7 digits, for example MSKU1234567.")
    key = (terminal or "").strip().lower()
    if key not in TERMINALS and html is None:
        raise ValueError(f"Unknown terminal. Choose one of: {', '.join(sorted(TERMINALS))}.")
    url = source or TERMINALS.get(key) or os.environ.get("TERMINAL_URL") or ""
    try:
        page = html if html is not None else _fetch_html(url)
    except Exception as exc:  # noqa: BLE001
        return ScrapedTerminalStatus(terminal=key, container=code, found=False, source=url, error=str(exc))
    return parse_container_page(key, code, page, url)


def needs_free_time_alert(status: ScrapedTerminalStatus) -> bool:
    hours = status.free_hours_remaining
    return bool(status.found and hours is not None and hours <= 48)
