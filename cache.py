"""Short-lived bot state. Uses Redis when REDIS_URL is set, otherwise files under state/."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
_CLIENT = None
_TRIED = False


def redis_client():
    global _CLIENT, _TRIED
    if _TRIED:
        return _CLIENT
    _TRIED = True
    url = os.environ.get("REDIS_URL") or ""
    if not url:
        return None
    import redis

    _CLIENT = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    return _CLIENT


def get_text(key: str) -> str | None:
    client = redis_client()
    if client is not None:
        try:
            return client.get(key)
        except Exception as exc:  # noqa: BLE001 — a down Redis must not stop a quote
            print(f"[cache] get {key}: {exc}")
    path = STATE / "cache" / key.replace(":", "_")
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        envelope = None
    if isinstance(envelope, dict) and envelope.get("__quote_cache__") == 1:
        if float(envelope["expires_at"]) <= time.time():
            path.unlink(missing_ok=True)
            return None
        return envelope["value"]
    # Respect the intended lifetime of files written before expiry metadata existed.
    legacy_ttl = 600 if key == "fx:market" else 86400 if key.startswith("dialog:") else 604800 if key.startswith("compare:") else None
    if legacy_ttl and path.stat().st_mtime + legacy_ttl <= time.time():
        path.unlink(missing_ok=True)
        return None
    return raw


def set_text(key: str, value: str, ttl: int | None = None) -> None:
    path = STATE / "cache" / key.replace(":", "_")
    client = redis_client()
    if client is not None:
        try:
            if ttl:
                client.set(key, value, ex=ttl)
            else:
                client.set(key, value)
            path.unlink(missing_ok=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] set {key}: {exc}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"__quote_cache__": 1, "expires_at": time.time() + ttl, "value": value}) if ttl else value
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(raw)
        temporary = handle.name
    os.replace(temporary, path)


def delete(key: str) -> None:
    client = redis_client()
    if client is not None:
        try:
            client.delete(key)
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] delete {key}: {exc}")
    path = STATE / "cache" / key.replace(":", "_")
    if path.is_file():
        path.unlink()


def get_json(key: str):
    raw = get_text(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        delete(key)
        return None


def set_json(key: str, value, ttl: int | None = None) -> None:
    set_text(key, json.dumps(value), ttl)
