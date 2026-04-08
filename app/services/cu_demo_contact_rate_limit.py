"""Simple in-memory sliding-window rate limit for public demo contact (per process)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException

from app.core.config import settings

_lock = threading.Lock()
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def _client_key_from_request(request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_cu_demo_contact_rate_limit(request) -> str:
    """
    Raises 429 if this client exceeded cu_demo_contact_rate_limit_per_minute in the last 60s.
    Returns the key used (for tests/logging).
    """
    key = _client_key_from_request(request) + ":cu_demo_contact"
    window_sec = 60
    max_req = max(1, int(settings.cu_demo_contact_rate_limit_per_minute or 8))
    now = time.monotonic()
    with _lock:
        dq = _buckets[key]
        cutoff = now - window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_req:
            raise HTTPException(
                status_code=429,
                detail="Too many demo requests from this network. Please wait a minute and try again.",
            )
        dq.append(now)
    return key
