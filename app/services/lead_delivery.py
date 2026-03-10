import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.lead_request import LeadRequest

logger = logging.getLogger(__name__)


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def build_lead_webhook_payload(row: LeadRequest) -> Dict[str, Any]:
    return {
        "lead_id": int(row.id),
        "created_at": _iso_or_none(row.created_at),
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "vin": row.vin,
        "year": row.year,
        "make": row.make,
        "model": row.model,
        "trim": row.trim,
        "vehicle": row.vehicle,
        "source": row.source,
        "notes": row.notes,
    }


def is_lead_webhook_enabled() -> bool:
    return bool((settings.lead_webhook_url or "").strip())


def _utcnow_naive() -> datetime:
    # DB columns use DateTime without timezone; store UTC timestamps as naive.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _update_lead_delivery_state(lead_id: Optional[int], **fields: Any) -> None:
    if not lead_id:
        return

    db = SessionLocal()
    try:
        row = db.query(LeadRequest).filter(LeadRequest.id == int(lead_id)).first()
        if not row:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist lead delivery status for lead_id=%s", lead_id)
    finally:
        db.close()


def send_lead_webhook(payload: Dict[str, Any]) -> None:
    url = (settings.lead_webhook_url or "").strip()
    lead_id = payload.get("lead_id")
    if not url:
        _update_lead_delivery_state(
            lead_id,
            webhook_status="skipped",
            webhook_last_error="LEAD_WEBHOOK_URL is not configured",
        )
        return

    timeout_seconds = max(int(settings.lead_webhook_timeout_seconds), 1)
    max_attempts = max(int(settings.lead_webhook_max_attempts), 1)
    base_backoff_seconds = max(float(settings.lead_webhook_retry_backoff_seconds), 0.0)

    headers = {"Content-Type": "application/json"}
    secret = (settings.lead_webhook_secret or "").strip()
    if secret:
        headers["X-Webhook-Secret"] = secret

    for attempt in range(1, max_attempts + 1):
        _update_lead_delivery_state(
            lead_id,
            webhook_status="pending",
            webhook_attempts=attempt,
            webhook_last_attempt_at=_utcnow_naive(),
            webhook_last_error=None,
        )
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            _update_lead_delivery_state(
                lead_id,
                webhook_status="sent",
                webhook_delivered_at=_utcnow_naive(),
                webhook_last_error=None,
            )
            return
        except httpx.HTTPError as exc:
            if attempt >= max_attempts:
                _update_lead_delivery_state(
                    lead_id,
                    webhook_status="failed",
                    webhook_last_error=str(exc),
                )
                logger.error(
                    "Lead webhook delivery failed after %s attempt(s) for lead_id=%s: %s",
                    max_attempts,
                    lead_id,
                    str(exc),
                )
                return

            if base_backoff_seconds <= 0:
                continue
            sleep_seconds = base_backoff_seconds * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)
