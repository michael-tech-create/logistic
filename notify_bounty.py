"""Drain durable, metadata-only quote notifications into the bounty inbox."""
import json
import os
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def notify_bounty(event_type: str, ref: str = "") -> bool:
    url = os.environ.get("BOUNTY_NOTIFY_URL", "").strip()
    token = os.environ.get("NOTIFY_INTERNAL_TOKEN", "").strip()
    if not url or not token or not ref:
        return False
    body = json.dumps({"type": event_type, "id": ref}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "X-API-Key": token})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as response:
            return response.status == 200
    except Exception:
        # Retain the outbox item for retry; never log URLs, tokens or quote data.
        return False


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    from bounty_bridge import deliver_pending
    deliver_pending(notify_bounty)
