#!/usr/bin/env python3
"""Send external health requests to reduce Render Free idle spin-down.

Run on another machine: python3 keep_render_awake.py
Run from a scheduler:  python3 keep_render_awake.py --once

RENDER_HEALTH_URL overrides the default service URL.
RENDER_PING_SECONDS overrides the default 300-second interval.
This cannot prevent platform restarts or suspension at usage limits.
"""

from __future__ import annotations

import argparse
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://logistic-ii6n.onrender.com/health"


def ping(url: str, *, attempts: int = 3) -> bool:
    """Allow cold starts and retry transient failures; report scheduler failures."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "quote-desk-keepalive/1.0",
        "Cache-Control": "no-cache",
    })
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                status = response.status
            if 200 <= status < 300:
                print(f"[keepalive] HTTP {status} {url}", flush=True)
                return True
            detail = f"HTTP {status}"
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code}"
            exc.close()
        except (OSError, urllib.error.URLError) as exc:
            detail = str(exc)
        print(f"[keepalive] attempt {attempt}/{attempts} failed: {detail}", flush=True)
        if attempt < attempts:
            time.sleep(10)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("RENDER_HEALTH_URL") or DEFAULT_URL)
    parser.add_argument("--interval", type=int, default=os.environ.get("RENDER_PING_SECONDS") or "300")
    parser.add_argument("--once", action="store_true", help="Exit after one check, including retries.")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        parser.error("--url must be an absolute http(s) health URL")
    if not 30 <= args.interval <= 600:
        parser.error("--interval must be between 30 and 600 seconds")
    try:
        if args.once:
            return 0 if ping(args.url) else 1
        print(f"[keepalive] pinging {args.url} every {args.interval}s; Ctrl+C stops it", flush=True)
        while True:
            started = time.monotonic()
            ping(args.url)
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\n[keepalive] stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
