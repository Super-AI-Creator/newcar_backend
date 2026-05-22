import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.email import EmailDeliveryError, send_email
from app.models.lead_request import LeadRequest
from app.services.ghl_contacts import create_ghl_contact_for_lead

logger = logging.getLogger(__name__)


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def build_lead_webhook_payload(row: LeadRequest) -> Dict[str, Any]:
    raw_notes = (row.notes or "").strip()
    notes = raw_notes if raw_notes else "No note"
    return {
        "event": "lead.submitted",
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
        "notes": notes,
    }


def is_trade_in_source(source: Optional[str]) -> bool:
    return str(source or "").strip().lower().startswith("trade_in")


def build_trade_in_webhook_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(payload)
    body["event"] = "trade_in.submitted"
    body["lead_type"] = "trade_in"
    body["formatted_plain"] = str(payload.get("notes") or "").strip()
    body["formatted_html"] = (
        "<pre style=\"font-family:system-ui,sans-serif;white-space:pre-wrap;line-height:1.4;\">"
        + str(payload.get("notes") or "").strip()
        + "</pre>"
    )
    return body


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


def process_new_lead_integrations(payload: Dict[str, Any]) -> None:
    """After a lead is stored: sync to GoHighLevel (when configured), then send the Make/webhook."""
    lead_source = payload.get("source")
    trade_in_lead = is_trade_in_source(lead_source)

    create_ghl_contact_for_lead(payload)

    if trade_in_lead:
        send_trade_in_email_notification(payload)
    if not is_lead_webhook_enabled():
        return

    webhook_payload = build_trade_in_webhook_payload(payload) if trade_in_lead else payload
    send_lead_webhook(webhook_payload)


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


def send_trade_in_email_notification(payload: Dict[str, Any]) -> None:
    to_email = (settings.trade_in_notify_email or settings.broker_email or "").strip()
    if not to_email:
        logger.warning("Trade-in email skipped: no TRADE_IN_NOTIFY_EMAIL or BROKER_EMAIL configured.")
        return

    lead_id = payload.get("lead_id")
    name = str(payload.get("name") or "").strip() or "Trade-in lead"
    email = str(payload.get("email") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    vehicle = str(payload.get("vehicle") or "").strip()
    source = str(payload.get("source") or "").strip() or "trade_in"
    notes = str(payload.get("notes") or "").strip() or "No notes provided."

    subject = f"Trade-in Lead #{lead_id} — {name}" if lead_id else f"Trade-in Lead — {name}"
    lines = [
        f"Lead ID: {lead_id or '—'}",
        f"Source: {source}",
        f"Name: {name}",
        f"Email: {email or '—'}",
        f"Phone: {phone or '—'}",
        f"Vehicle: {vehicle or '—'}",
        "",
        "Trade-in details:",
        notes,
    ]
    plain = "\n".join(lines)
    html = (
        "<p style=\"font-family:system-ui,sans-serif;font-size:14px;color:#333;\">"
        f"<strong>Lead ID:</strong> {lead_id or '—'}<br/>"
        f"<strong>Source:</strong> {source}<br/>"
        f"<strong>Name:</strong> {name}<br/>"
        f"<strong>Email:</strong> {email or '—'}<br/>"
        f"<strong>Phone:</strong> {phone or '—'}<br/>"
        f"<strong>Vehicle:</strong> {vehicle or '—'}"
        "</p>"
        "<pre style=\"font-family:system-ui,sans-serif;white-space:pre-wrap;line-height:1.4;border:1px solid #ddd;padding:12px;border-radius:8px;\">"
        + notes
        + "</pre>"
    )
    try:
        send_email(to_email=to_email, subject=subject, body=plain, html_body=html)
    except EmailDeliveryError:
        logger.exception("Trade-in email delivery failed for lead_id=%s", lead_id)
