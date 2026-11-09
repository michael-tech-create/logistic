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


def register_webhook(config, url):
    """Register this app's message webhook using WaAPI's update-instance API."""
    import json
    import urllib.request
    from urllib.error import HTTPError
    request = urllib.request.Request(
        f"https://waapi.app/api/v1/instances/{config['instance_id']}",
        method="PUT", data=json.dumps({"webhook": {"url": url, "events": ["message"]}}).encode(),
        headers={"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    # Never follow redirects with credentials, or expose the provider's raw errors.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            result = json.loads(response.read(1024 * 1024))
        if result.get("status") != "success":
            raise ValueError("WaAPI did not confirm setup. Check your token and instance ID, then retry.")
    except HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise ValueError("WaAPI rejected these details. Check the token, instance ID, and the token’s update permission.") from None
        raise ValueError("WaAPI could not complete setup. Please retry shortly.") from None
    except ValueError:
        raise
    except Exception:
        raise ValueError("WaAPI did not confirm setup. Your details are saved; retry to finish connecting.") from None
