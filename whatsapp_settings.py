"""Workspace-owned provider settings in the private operational store.

Only the API's database identity can read this namespace on hosted deployments.
Never return provider tokens from a public settings response.
"""
import os
from contextvars import ContextVar
import operations_store as state

current_company = ContextVar("whatsapp_company", default=None)
active_settings = ContextVar("whatsapp_settings", default=None)


def saved(company):
    return state.get("wa_settings", company) if company else None


def settings(company=None):
    company = company or current_company.get()
    snapshot = active_settings.get()
    if snapshot and company == current_company.get():
        return snapshot
    row = saved(company)
    if row:
        return row["payload"]
    return {
        "token": os.environ.get("WAAPI_TOKEN", ""),
        "instance_id": os.environ.get("WAAPI_INSTANCE_ID", ""),
        "webhook_secret": os.environ.get("WAAPI_WEBHOOK_SECRET", ""),
        "business_number": os.environ.get("WHATSAPP_BUSINESS_NUMBER", ""),
    }
