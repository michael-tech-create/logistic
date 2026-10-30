"""Workspace-scoped channel connections, sourced calculations, and measurements."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field
import operations_store as state
from shipment_costs import CustomsValue, TariffProfile, ShipmentStorage, customs_cost, storage_cost, today_lagos

router = APIRouter()


def _owner(authorization, x_api_key):
    from api.main import current_user, ensure_company
    user = current_user(authorization, x_api_key)
    return user, ensure_company(user)["code"]


@router.get("/v1/tariffs")
def tariffs(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    _, company = _owner(authorization, x_api_key)
    return {"profiles": [row["payload"] for row in state.listing("tariffs", company)]}


@router.post("/v1/tariffs")
def save_tariff(body: TariffProfile, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user, company = _owner(authorization, x_api_key)
    data = body.model_dump(mode="json")
    state.put("tariffs", company + ":" + body.hs_code, data, company)
    return data


@router.post("/v1/quotes/{record_id}/customs")
def calculate_customs(record_id: str, body: CustomsValue, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from api.main import _owned_quote, _save_desk_quote
    user, company = _owner(authorization, x_api_key)
    record = _owned_quote(user, record_id)
    profile = state.get("tariffs", company + ":" + body.hs_code)
    if not profile or profile["company_id"] != company: raise HTTPException(400, "Save a reviewed tariff profile for this HS code first.")
    try: calculation = customs_cost(body, TariffProfile.model_validate(profile["payload"]))
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    calculation["calculated_at"] = datetime.now(timezone.utc).isoformat()
    calculation["reviewed_by"] = user["email"]
    record["customs_assessment"] = record["duty_estimate"] = calculation
    record.pop("desk_review", None)
    return _save_desk_quote(record, user)


@router.post("/v1/quotes/{record_id}/storage")
def calculate_storage(record_id: str, body: ShipmentStorage, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from api.main import _owned_quote, _save_desk_quote
    user, company = _owner(authorization, x_api_key)
    record = _owned_quote(user, record_id)
    calculation = storage_cost(body)
    calculation["calculated_at"] = datetime.now(timezone.utc).isoformat()
    rows = [item for item in record.get("storage_assessments", []) if (item["container"], item["charge_type"]) != (body.container, body.charge_type)]
    if len(rows) >= 20: raise HTTPException(400, "Use at most 20 shipment charge schedules per quote.")
    record["storage_assessments"] = [*rows, calculation]
    record.pop("desk_review", None)
    result = _save_desk_quote(record, user)
    key = f"{company}:{record_id}:{body.container}:{body.charge_type}"
    state.put("shipment_watches", key, {"record_id": record_id, "inputs": body.model_dump(mode="json")}, company)
    return result


@router.get("/v1/shipments/alerts")
def alerts(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    user, company = _owner(authorization, x_api_key)
    from api.main import _owned_quote
    items = []
    for row in state.listing("shipment_watches", company, limit=100):
        try: _owned_quote(user, row["payload"]["record_id"])
        except HTTPException as exc:
            if exc.status_code == 404: continue
            raise
        inputs = {**row["payload"]["inputs"], "as_of_date": today_lagos().isoformat()}
        try:
            result = storage_cost(ShipmentStorage.model_validate(inputs))
        except ValueError:
            result = {"status": "source_review_needed", "container": inputs["container"], "charge_type": inputs["charge_type"], "reason": "Review the rate source and its effective dates before relying on a current charge."}
        if result["status"] != "within_free_time": items.append({**result, "record_id": row["payload"]["record_id"]})
    return {"as_of": today_lagos().isoformat(), "alerts": items}


@router.get("/v1/operations/performance")
def performance(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from api.main import inbox
    records = inbox(authorization, x_api_key)["records"]
    values = sorted(float(record["processing"]["milliseconds"]) for record in records if record.get("processing", {}).get("milliseconds") is not None)
    import math
    return {"samples": len(values), "p50_ms": values[max(0, math.ceil(len(values) * .5) - 1)] if values else None, "p95_ms": values[max(0, math.ceil(len(values) * .95) - 1)] if values else None, "under_five_seconds": sum(value <= 5000 for value in values), "scope": "Recent workspace preparation timings. Each quote shows its measurement scope; queue time, final delivery, export, and human review are excluded. This is not an end-to-end speed guarantee."}


@router.get("/v1/channels/whatsapp")
def whatsapp_status(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from whatsapp_intake import configured
    _, company = _owner(authorization, x_api_key)
    number = os.environ.get("WHATSAPP_BUSINESS_NUMBER", "")
    # Report presence/format only; provider credentials never leave the server.
    checks = {
        "storage": False,
        "provider_token": bool(os.environ.get("WAAPI_TOKEN")),
        "instance_id": os.environ.get("WAAPI_INSTANCE_ID", "").isdigit(),
        "webhook_secret": len(os.environ.get("WAAPI_WEBHOOK_SECRET", "")) >= 32,
        "business_number": bool(re.fullmatch(r"\d{8,16}", number)),
    }
    try:
        state.require_intake_storage()
        checks["storage"] = True
        links = [{"phone": row["key"].split("@")[0]} for row in state.listing("wa_links", company) if row["payload"].get("active")]
    except state.StorageSetupError as exc:
        return {"configured": False, "links": [], "url": None, "setup_required": True, "detail": str(exc), "checks": checks}
    except Exception as exc:
        raise HTTPException(503, "WhatsApp connections could not be loaded. Please try again shortly.") from exc
    ready = configured()
    return {"configured": ready, "links": links, "url": f"https://wa.me/{number}" if checks["business_number"] else None, "setup_required": not ready, "detail": None if ready else "Finish the one-time provider and webhook setup below, then connect your number.", "checks": checks}


@router.post("/v1/channels/whatsapp/link")
def new_whatsapp_code(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from whatsapp_intake import configured, link_code
    _, company = _owner(authorization, x_api_key)
    if not configured(): raise HTTPException(503, "WhatsApp intake is not connected yet. Ask your administrator to finish setup.")
    try:
        state.require_intake_storage()
        return link_code(company)
    except state.StorageSetupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "A WhatsApp connection code could not be created. Please try again shortly.") from exc


class Disconnect(BaseModel):
    phone: str = Field(pattern=r"^\d{8,16}$")


@router.post("/v1/channels/whatsapp/disconnect")
def disconnect_whatsapp(body: Disconnect, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    _, company = _owner(authorization, x_api_key)
    try:
        state.require_intake_storage()
        row = state.get("wa_links", body.phone + "@c.us")
    except state.StorageSetupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "WhatsApp connections could not be loaded. Please try again shortly.") from exc
    if not row or row["company_id"] != company: raise HTTPException(404, "Connection not found.")
    if not state.put("wa_links", row["key"], {"active": False}, company, expected=row["revision"]):
        raise HTTPException(409, "The connection changed. Refresh and try again.")
    return {"disconnected": True}


class _HideWebhookToken(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(re.sub(r"/whatsapp/webhook/[^ ?]+", "/whatsapp/webhook/[redacted]", value) if isinstance(value, str) else value for value in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_HideWebhookToken())


@router.post("/whatsapp/webhook/{token}")
async def whatsapp_webhook(token: str, request: Request, background_tasks: BackgroundTasks):
    from whatsapp_intake import enqueue, schedule_pending
    secret = os.environ.get("WAAPI_WEBHOOK_SECRET", "")
    if len(secret) < 32: raise HTTPException(503, "WhatsApp intake is not configured.")
    if not secrets.compare_digest(token, secret): raise HTTPException(401, "Invalid webhook credentials.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024: raise HTTPException(413, "Webhook payload is too large.")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict): raise ValueError
        job = enqueue(payload)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "Invalid WhatsApp event.") from exc
    except Exception as exc:
        raise HTTPException(503, "Intake storage is unavailable.") from exc
    if job: background_tasks.add_task(schedule_pending)
    return {"accepted": True, "queued": bool(job)}
