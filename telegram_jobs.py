"""Durable Telegram intake jobs, shared by polling and webhook delivery."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

QUEUE_PATH = Path(os.environ.get("TELEGRAM_QUEUE_DB", Path(__file__).resolve().parent / "state" / "telegram_jobs.sqlite"))
_RUNNING: set[int] = set()
_CHATS: set[str] = set()
_RUNNING_LOCK = threading.Lock()


def _connect():
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(QUEUE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_jobs (
        update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, chat_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
        claimed_at REAL NOT NULL DEFAULT 0
    )""")
    return conn


def enqueue(update: dict) -> int:
    update_id = update.get("update_id")
    if not isinstance(update_id, int) or isinstance(update_id, bool):
        raise ValueError("A Telegram update_id is required.")
    message = (update.get("callback_query") or {}).get("message") or update.get("message") or update.get("channel_post") or {}
    chat_key = str((message.get("chat") or {}).get("id") or f"update-{update_id}")
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO telegram_jobs (update_id, payload, chat_key) VALUES (?, ?, ?)", (update_id, json.dumps(update), chat_key))
    return update_id


def _claim(update_id: int) -> dict | None:
    now = time.time()
    with _connect() as conn:
        changed = conn.execute("""UPDATE telegram_jobs SET status='processing', attempts=attempts+1, claimed_at=?
            WHERE update_id=? AND attempts<3 AND available_at<=?
            AND (status='pending' OR (status='processing' AND claimed_at<?))
            AND NOT EXISTS (SELECT 1 FROM telegram_jobs AS older WHERE older.chat_key=telegram_jobs.chat_key
                AND older.update_id<telegram_jobs.update_id AND older.status IN ('pending','processing'))""", (now, update_id, now, now - 900)).rowcount
        if not changed:
            return None
        payload = conn.execute("SELECT payload FROM telegram_jobs WHERE update_id=?", (update_id,)).fetchone()["payload"]
    return json.loads(payload)


def run_job(update_id: int) -> None:
    update = _claim(update_id)
    if update is None:
        return
    from automate import process_telegram_update

    try:
        ok = process_telegram_update(update)
    except Exception:
        ok = False
    with _connect() as conn:
        if ok:
            # Keep the delivery ID for deduplication without retaining the raw chat update.
            conn.execute("UPDATE telegram_jobs SET status='done', payload='{}' WHERE update_id=?", (update_id,))
        else:
            conn.execute("""UPDATE telegram_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
                available_at=? WHERE update_id=?""", (time.time() + 30, update_id))


def schedule_pending() -> None:
    from workers import submit

    now = time.time()
    with _connect() as conn:
        # A process can disappear after its final claim. Do not leave that chat stuck forever.
        conn.execute("UPDATE telegram_jobs SET status='failed' WHERE status='processing' AND attempts>=3 AND claimed_at<?", (now - 900,))
        rows = conn.execute("""SELECT update_id, chat_key FROM telegram_jobs WHERE attempts<3 AND available_at<=?
            AND (status='pending' OR (status='processing' AND claimed_at<?)) ORDER BY update_id LIMIT 200""", (now, now - 900)).fetchall()
    for row in rows:
        update_id = row["update_id"]
        with _RUNNING_LOCK:
            if update_id in _RUNNING or row["chat_key"] in _CHATS or len(_RUNNING) >= 4:
                continue
            _RUNNING.add(update_id)
            _CHATS.add(row["chat_key"])
        try:
            future = submit(run_job, update_id)
        except Exception:
            with _RUNNING_LOCK:
                _RUNNING.discard(update_id)
                _CHATS.discard(row["chat_key"])
            raise
        def finished(_future, job_id=update_id, chat_key=row["chat_key"]):
            with _RUNNING_LOCK:
                _RUNNING.discard(job_id)
                _CHATS.discard(chat_key)
        future.add_done_callback(finished)
