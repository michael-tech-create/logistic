"""Auditable estimates from explicit valuation, dated tariffs, and shipment terms."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo
import re
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    url: HttpUrl
    effective_from: date
    effective_to: date
    reviewed: bool

    @model_validator(mode="after")
    def valid(self):
        if not self.reviewed: raise ValueError("Review the source before using its rates.")
        if self.effective_to < self.effective_from: raise ValueError("The source end date must follow its start date.")
        return self


class TariffCharge(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    label: str = Field(min_length=2, max_length=100)
    rate_percent: Decimal = Field(ge=0, le=1000)
    bases: list[str] = Field(min_length=1, max_length=20)


class TariffProfile(StrictModel):
    hs_code: str = Field(pattern=r"^\d{8}(\d{2})?$")
    description: str = Field(min_length=3, max_length=300)
    source: Source
    charges: list[TariffCharge] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_bases(self):
        available = {"cif", "fob"}
        for charge in self.charges:
            if charge.code in available: raise ValueError("Each charge needs a unique code.")
            if len(set(charge.bases)) != len(charge.bases) or not set(charge.bases) <= available:
                raise ValueError("Charge bases must be CIF, FOB, or earlier charges, each used once.")
            if "cif" in charge.bases and "fob" in charge.bases:
                raise ValueError("CIF already contains FOB; do not add both to a tax base.")
            available.add(charge.code)
        return self


class CustomsValue(StrictModel):
    hs_code: str = Field(pattern=r"^\d{8}(\d{2})?$")
    assessment_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    goods_value: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    freight: Decimal = Field(ge=0, le=Decimal("1000000000000"))
    insurance: Decimal = Field(ge=0, le=Decimal("1000000000000"))
    adjustments: Decimal = Field(default=0, ge=0, le=Decimal("1000000000000"))
    ngn_per_unit: Decimal = Field(gt=0, le=Decimal("1000000000"))
    rate_date: date
    rate_source: HttpUrl
    valuation_reference: str = Field(min_length=3, max_length=200)
    confirmed: bool

    @model_validator(mode="after")
    def verified(self):
        if not self.confirmed: raise ValueError("Confirm the goods value, classification, and assessment exchange rate.")
        if self.currency == "NGN" and self.ngn_per_unit != 1: raise ValueError("The NGN conversion rate must be 1.")
        if self.rate_date != self.assessment_date: raise ValueError("Use the customs exchange rate effective on the assessment date.")
        return self


def _amount(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def customs_cost(value: CustomsValue, profile: TariffProfile) -> dict:
    if value.hs_code != profile.hs_code: raise ValueError("The tariff profile must match the shipment HS code.")
    if not profile.source.effective_from <= value.assessment_date <= profile.source.effective_to:
        raise ValueError("This tariff profile is not effective on the assessment date. Review and update it first.")
    rate = value.ngn_per_unit
    bases = {"fob": value.goods_value * rate, "cif": (value.goods_value + value.freight + value.insurance + value.adjustments) * rate}
    lines = []
    for charge in profile.charges:
        base = sum(bases[key] for key in charge.bases)
        amount = (base * charge.rate_percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        bases[charge.code] = amount
        lines.append({"code": charge.code, "label": charge.label, "bases": charge.bases, "base_ngn": _amount(base), "rate_percent": float(charge.rate_percent), "amount_ngn": _amount(amount)})
    total = sum(bases[line.code] for line in profile.charges)
    return {"status": "calculated", "hs_code": value.hs_code, "label": profile.description, "currency": "NGN", "cif_ngn": _amount(bases["cif"]), "total_ngn": _amount(total), "landed_value_ngn": _amount(bases["cif"] + total), "lines": lines, "inputs": value.model_dump(mode="json"), "tariff": profile.model_dump(mode="json"), "basis": "Estimate from the supplied valuation and operator-reviewed tariff source. Final assessment remains with Nigeria Customs Service."}


class StorageTier(StrictModel):
    through_day: int | None = Field(default=None, ge=1, le=3650)
    daily_rate: Decimal = Field(ge=0, le=Decimal("1000000000"))


class ShipmentStorage(StrictModel):
    container: str = Field(pattern=r"^[A-Z]{4}\d{7}$")
    charge_type: Literal["demurrage", "detention", "terminal_storage"] = "demurrage"
    last_free_date: date
    as_of_date: date
    quantity: int = Field(default=1, ge=1, le=1000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    day_basis: Literal["calendar", "business"] = "calendar"
    holidays: list[date] = Field(default_factory=list, max_length=100)
    tiers: list[StorageTier] = Field(min_length=1, max_length=20)
    source: Source

    @model_validator(mode="after")
    def ordered(self):
        previous = 0
        for index, tier in enumerate(self.tiers):
            if tier.through_day is None:
                if index != len(self.tiers) - 1: raise ValueError("Only the final rate tier can be open-ended.")
            elif tier.through_day <= previous: raise ValueError("Rate tiers must end on increasing chargeable days.")
            else: previous = tier.through_day
        if self.tiers[-1].through_day is not None: raise ValueError("Add an open-ended final daily rate.")
        if abs((self.as_of_date - self.last_free_date).days) > 3650: raise ValueError("Check the shipment dates; they are more than ten years apart.")
        start = min(self.as_of_date, self.last_free_date + timedelta(days=1))
        if not self.source.effective_from <= start <= self.as_of_date <= self.source.effective_to:
            raise ValueError("The rate source must cover the whole calculation period.")
        return self


def storage_cost(shipment: ShipmentStorage) -> dict:
    cursor = shipment.last_free_date + timedelta(days=1)
    days = 0
    while cursor <= shipment.as_of_date:
        if shipment.day_basis == "calendar" or cursor.weekday() < 5 and cursor not in shipment.holidays:
            days += 1
        cursor += timedelta(days=1)
    charged = 0; total = Decimal(0); lines = []
    for tier in shipment.tiers:
        count = max(0, min(days, tier.through_day if tier.through_day is not None else days) - charged)
        amount = count * tier.daily_rate * shipment.quantity
        lines.append({"days": count, "daily_rate": _amount(tier.daily_rate), "quantity": shipment.quantity, "amount": _amount(amount)})
        total += amount; charged += count
    remaining = (shipment.last_free_date - shipment.as_of_date).days
    return {"status": "overdue" if days else "due_soon" if remaining <= 2 else "within_free_time", "container": shipment.container, "charge_type": shipment.charge_type, "currency": shipment.currency, "chargeable_days": days, "days_until_last_free_date": max(0, remaining), "total": _amount(total), "lines": lines, "inputs": shipment.model_dump(mode="json"), "basis": "Calculated from the supplied carrier or terminal free-time date and rate schedule; verify these against the shipment contract."}


def source_hints(text: str) -> dict:
    """Extract identifiers for review without guessing a goods value or rate."""
    hs = re.search(r"\b(?:HS(?:\s*code)?|tariff\s*code)\s*[:#-]?\s*(\d{4}[. ]?\d{2}[. ]?\d{2}(?:[. ]?\d{2})?)\b", text, re.I)
    container = re.search(r"\b[A-Z]{4}\d{7}\b", text.upper())
    return {"hs_code": re.sub(r"\D", "", hs.group(1)) if hs else None, "container": container.group() if container else None}


def today_lagos():
    return datetime.now(ZoneInfo("Africa/Lagos")).date()
