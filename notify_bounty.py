"""Tell the bounty agent's inbox that a quote event exists.

The body is only an event type and an id. Customer quote text stays here.
"""

import json
import os
import urllib.request


def notify_bounty(event_type: str, ref: str = "") -> None:
    url = os.environ.get("BOUNTY_NOTIFY_URL", "").strip()
    token = os.environ.get("NOTIFY_INTERNAL_TOKEN", "").strip()
    if not url or not token or not event_type:
        return
    body = json.dumps({"type": event_type, "id": ref}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": token},
    )
    urllib.request.urlopen(req, timeout=10).read()
