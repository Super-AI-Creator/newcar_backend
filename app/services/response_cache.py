from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "ncs-cache:v1"
_HTTP_TIMEOUT_SECONDS = 1.2


def _cache_enabled() -> bool:
    return bool((settings.cache_rest_url or "").strip() and (settings.cache_rest_token or "").strip())


def _redis_key(namespace: str, raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"{_CACHE_KEY_PREFIX}:{namespace}:{digest}"


def _run_command(*parts: Any) -> Optional[Any]:
    base_url = (settings.cache_rest_url or "").strip()
    token = (settings.cache_rest_token or "").strip()
    if not base_url or not token:
        return None

    url = base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=list(parts))
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get("result")
    except Exception:
        logger.debug("Shared cache command failed", exc_info=True)
    return None


def get_shared_json(namespace: str, raw_key: str) -> Optional[Any]:
    if not _cache_enabled():
        return None
    result = _run_command("GET", _redis_key(namespace, raw_key))
    if not isinstance(result, str) or not result.strip():
        return None
    try:
        parsed = json.loads(result)
    except Exception:
        return None
    return parsed


def set_shared_json(namespace: str, raw_key: str, payload: Any, ttl_seconds: Optional[int] = None) -> None:
    if not _cache_enabled():
        return
    ttl = int(ttl_seconds or settings.cache_default_ttl_seconds)
    ttl = max(30, ttl)
    try:
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return
    _run_command("SETEX", _redis_key(namespace, raw_key), ttl, serialized)

