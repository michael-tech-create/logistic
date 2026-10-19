"""Branded Excel and PDF packs for a clearing agent."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pypdf import PdfReader
from fpdf import FPDF


def new_pdf() -> FPDF:
    """Bundle the font so naira signs and common Unicode work in Docker too."""
    pdf = FPDF()
    fonts = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    for style, filename in (("", "DejaVuSans.ttf"), ("B", "DejaVuSans-Bold.ttf"), ("I", "DejaVuSans-Oblique.ttf")):
        pdf.add_font("Desk", style, str(fonts / filename))
    return pdf


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def build_xlsx(records: list[dict], business_name: str) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Quotes"
    headers = [
        "Business", "Lane", "Vendor", "Reference", "Quote date", "Valid until",
        "Origin", "Origin code", "Destination", "Destination code", "Mode",
        "Incoterms", "Currency", "Description", "Category", "Amount", "Quote total", "Flags",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0B3954")
    for record in records:
        commercial = record["commercial"]
        movement = record["movement"]
        flags = "; ".join(record.get("extraction_flags") or [])
        items = record.get("line_items") or [{}]
        for item in items:
            sheet.append([
                business_name,
                record.get("lane"),
                commercial.get("vendor_name"),
                commercial.get("quote_reference_id"),
                commercial.get("quote_date"),
                commercial.get("valid_until"),
                (movement.get("origin") or {}).get("location_name"),
                (movement.get("origin") or {}).get("port_code"),
                (movement.get("destination") or {}).get("location_name"),
                (movement.get("destination") or {}).get("port_code"),
                movement.get("mode"),
                commercial.get("incoterms"),
                commercial.get("currency"),
                item.get("description"),
                item.get("category"),
                item.get("amount"),
                commercial.get("total_amount"),
                flags,
            ])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def build_pdf(records: list[dict], business_name: str) -> bytes:
    pdf = new_pdf()
    pdf.set_auto_page_break(auto=True, margin=16)
    for record in records:
        commercial = record["commercial"]
        movement = record["movement"]
        origin = movement.get("origin") or {}
        destination = movement.get("destination") or {}
        pdf.add_page()
        pdf.set_fill_color(11, 57, 84)
        pdf.rect(0, 0, 210, 22, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Desk", "B", 14)
        pdf.set_xy(12, 7)
        pdf.cell(0, 8, business_name)
        pdf.set_text_color(23, 35, 45)
        pdf.set_xy(12, 30)
        pdf.set_font("Desk", "B", 12)
        title = f"{commercial.get('vendor_name') or 'Quote'}  {commercial.get('quote_reference_id') or ''}"
        pdf.multi_cell(186, 8, title.strip())
        pdf.set_x(12)
        pdf.set_font("Desk", "", 11)
        rows = [
            f"Lane: {record.get('lane')}",
            f"Route: {origin.get('location_name') or '-'} ({origin.get('port_code') or '-'}) to {destination.get('location_name') or '-'} ({destination.get('port_code') or '-'})",
            f"Mode: {movement.get('mode')}    Transit: {movement.get('est_transit_days') or '-'} days",
            f"Incoterms: {commercial.get('incoterms') or '-'}    Payment: {commercial.get('payment_terms') or '-'}",
            f"Total: {commercial.get('currency')} {commercial.get('total_amount')}",
        ]
        for row in rows:
            pdf.set_x(12)
            pdf.multi_cell(186, 7, row)
        pdf.ln(2)
        pdf.set_x(12)
        pdf.set_font("Desk", "B", 11)
        pdf.cell(186, 7, "Charges", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Desk", "", 10)
        for item in record.get("line_items") or []:
            pdf.set_x(12)
            pdf.multi_cell(186, 6, f"{item.get('description')}  [{item.get('category')}]  {commercial.get('currency')} {item.get('amount')}")
        pdf.ln(4)
        pdf.set_x(12)
        pdf.set_font("Desk", "I", 8)
        pdf.multi_cell(186, 5, record.get("disclaimer") or "")
    return bytes(pdf.output())
