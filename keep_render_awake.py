#!/usr/bin/env python3
"""Ping the Render web service so a free instance does not spin down.

A sleeping instance stops Telegram long-polling. Render idles a free web
service after about 15 minutes with no HTTP traffic. This script hits
GET /health every 10 minutes. The first request can take a minute while
the instance boots.

  RENDER_HEALTH_URL   default https://logistic-ii6n.onrender.com/health
  RENDER_PING_SECONDS default 600

Run: .venv/bin/python keep_render_awake.py
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("RENDER_HEALTH_URL", "https://logistic-ii6n.onrender.com/health")
INTERVAL = int(os.environ.get("RENDER_PING_SECONDS", "600"))


def ping() -> None:
    request = urllib.request.Request(URL, headers={"User-Agent": "quote-desk-keepalive"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            print(f"[keepalive] {response.status} {URL}", flush=True)
    except urllib.error.HTTPError as exc:
        print(f"[keepalive] HTTP {exc.code} {URL}", flush=True)
    except OSError as exc:
        print(f"[keepalive] {exc}", flush=True)


def main() -> None:
    print(f"[keepalive] pinging {URL} every {INTERVAL}s", flush=True)
    while True:
        ping()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
