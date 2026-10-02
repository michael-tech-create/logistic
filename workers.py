"""Background workers for voice transcription and PDF text extraction."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="quote-worker")


def submit(func, *args, **kwargs) -> Future:
    return _POOL.submit(func, *args, **kwargs)
