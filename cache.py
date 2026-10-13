"""Short-lived bot state. Uses Redis when REDIS_URL is set, otherwise files under state/."""

from __future__ import annotations

import json
import os
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
    return path.read_text(encoding="utf-8")


def set_text(key: str, value: str, ttl: int | None = None) -> None:
    client = redis_client()
    if client is not None:
        try:
            if ttl:
                client.set(key, value, ex=ttl)
            else:
                client.set(key, value)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] set {key}: {exc}")
    path = STATE / "cache" / key.replace(":", "_")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def delete(key: str) -> None:
    client = redis_client()
    if client is not None:
        try:
            client.delete(key)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] delete {key}: {exc}")
    path = STATE / "cache" / key.replace(":", "_")
    if path.is_file():
        path.unlink()


def get_json(key: str):
    raw = get_text(key)
    if not raw:
        return None
    return json.loads(raw)


def set_json(key: str, value, ttl: int | None = None) -> None:
    set_text(key, json.dumps(value), ttl)
