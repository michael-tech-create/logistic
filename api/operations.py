"""Workspace-scoped channel connections, sourced calculations, and measurements."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
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


class WhatsAppSettings(BaseModel):
    token: SecretStr | None = None
    instance_id: str = Field(pattern=r"^[0-9]{1,30}$")
    business_number: str = Field(pattern=r"^[0-9]{8,16}$")


@router.put("/v1/channels/whatsapp/settings")
def save_whatsapp_settings(body: WhatsAppSettings, request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from whatsapp_settings import saved, register_webhook
    import time
    _, company = _owner(authorization, x_api_key)
    lock = None
    try:
        state.require_intake_storage()
        previous_lock = state.get("wa_setup_locks", company)
        if previous_lock and previous_lock["payload"].get("until", 0) > time.time():
            raise HTTPException(409, "Setup is already running. Wait a moment, then refresh.")
        lock = state.put("wa_setup_locks", company, {"until": time.time() + 120}, company, expected=previous_lock["revision"] if previous_lock else 0)
        if not lock: raise HTTPException(409, "Setup is already running. Please retry shortly.")
        old = saved(company)
        previous = old["payload"] if old else {}
        token = body.token.get_secret_value().strip() if body.token else previous.get("token", "")
        if not token or len(token) > 4096 or any(char.isspace() for char in token):
            raise HTTPException(400, "Enter a valid WaAPI token without spaces.")
        config = {"token": token, "instance_id": body.instance_id, "business_number": body.business_number,
                  "webhook_secret": previous.get("webhook_secret") or secrets.token_urlsafe(32), "webhook_ready": False}
        url = str(request.url_for("workspace_whatsapp_webhook", company=company, token=config["webhook_secret"]))
        if not url.startswith("https://"):
            raise HTTPException(400, "Open the public HTTPS version of this app to connect WhatsApp. WaAPI needs a reachable webhook address.")
        row = state.put("wa_settings", company, config, company, expected=old["revision"] if old else 0)
        if not row: raise HTTPException(409, "Settings changed. Refresh and retry.")
        try:
            register_webhook(config, url)
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from None
        if not state.put("wa_settings", company, {**config, "webhook_ready": True}, company, expected=row["revision"]):
            raise HTTPException(409, "Settings changed. Retry setup to confirm the connection.")
        return {"saved": True, "webhook_ready": True}
    except HTTPException:
        raise
    except state.StorageSetupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "WhatsApp setup could not be completed. Please retry.") from exc
    finally:
        if lock:
            state.put("wa_setup_locks", company, {"until": 0}, company, expected=lock["revision"])


@router.get("/v1/channels/whatsapp")
def whatsapp_status(response: Response, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from whatsapp_intake import configured
    from whatsapp_settings import settings, saved
    _, company = _owner(authorization, x_api_key)
    response.headers["Cache-Control"] = "no-store"
    checks = {"storage": False}
    try:
        state.require_intake_storage()
        checks["storage"] = True
        links = [{"phone": row["key"].split("@")[0]} for row in state.listing("wa_links", company) if row["payload"].get("active")]
        config = settings(company)
        custom = saved(company)
        ready = configured(company)
    except state.StorageSetupError as exc:
        return {"configured": False, "links": [], "url": None, "setup_required": True, "storage_ready": False, "detail": str(exc), "checks": checks}
    except Exception as exc:
        raise HTTPException(503, "WhatsApp connections could not be loaded. Please try again shortly.") from exc
    number = config["business_number"]
    checks.update(provider_token=bool(config["token"]), instance_id=config["instance_id"].isdigit(), webhook_secret=len(config["webhook_secret"]) >= 32, business_number=bool(re.fullmatch(r"\d{8,16}", number)))
    return {"configured": ready, "links": links, "url": f"https://wa.me/{number}" if checks["business_number"] else None,
            "setup_required": not ready, "storage_ready": True, "settings_saved": bool(custom), "token_saved": bool(custom),
            "instance_id": config["instance_id"] if custom else "", "business_number": number,
            "webhook_ready": bool(custom and config.get("webhook_ready")), "checks": checks,
            "detail": None if ready else "Enter your WhatsApp details below. We will configure the webhook automatically."}


@router.post("/v1/channels/whatsapp/link")
def new_whatsapp_code(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    from whatsapp_intake import configured, link_code
    _, company = _owner(authorization, x_api_key)
    try:
        state.require_intake_storage()
        if not configured(company): raise HTTPException(503, "Save and connect your WhatsApp account first.")
        return link_code(company)
    except HTTPException:
        raise
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


@router.post("/whatsapp/webhook/{company}/{token}")
async def workspace_whatsapp_webhook(company: str, token: str, request: Request, background_tasks: BackgroundTasks):
    from whatsapp_settings import saved
    try:
        row = saved(company)
    except Exception as exc:
        raise HTTPException(503, "Intake storage is unavailable.") from exc
    if not row or not secrets.compare_digest(token, row["payload"]["webhook_secret"]):
        raise HTTPException(401, "Invalid webhook credentials.")
    return await _receive_whatsapp(request, background_tasks, company)


@router.post("/whatsapp/webhook/{token}")
async def whatsapp_webhook(token: str, request: Request, background_tasks: BackgroundTasks):
    secret = os.environ.get("WAAPI_WEBHOOK_SECRET", "")
    if len(secret) < 32: raise HTTPException(503, "WhatsApp intake is not configured.")
    if not secrets.compare_digest(token, secret): raise HTTPException(401, "Invalid webhook credentials.")
    return await _receive_whatsapp(request, background_tasks)


async def _receive_whatsapp(request, background_tasks, company=None):
    from whatsapp_intake import enqueue, schedule_pending
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024: raise HTTPException(413, "Webhook payload is too large.")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict): raise ValueError
        job = enqueue(payload, company)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "Invalid WhatsApp event.") from exc
    except Exception as exc:
        raise HTTPException(503, "Intake storage is unavailable.") from exc
    if job: background_tasks.add_task(schedule_pending)
    return {"accepted": True, "queued": bool(job)}
