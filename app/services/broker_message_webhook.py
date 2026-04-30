"""POST Deal Room customer messages to Make.com (or any URL) for GoHighLevel workflows."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.broker_message import BrokerMessage
from app.models.user import User
from app.services.broker_messages import parse_message_from_storage
from app.services.ghl_contacts import lookup_ghl_contact_by_email

logger = logging.getLogger(__name__)


def is_broker_message_webhook_enabled() -> bool:
    return bool((settings.broker_message_webhook_url or "").strip())


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def build_broker_customer_message_payload(msg: BrokerMessage, user: User) -> Dict[str, Any]:
    sender_type, body = parse_message_from_storage(msg.message_text or "")
    ghl_contact_id: Optional[str] = None
    ghl_lookup = "skipped"
    if (settings.ghl_private_integration_token or "").strip() and (settings.ghl_location_id or "").strip():
        ghl_contact_id, ghl_lookup = lookup_ghl_contact_by_email(user.email)

    return {
        "event": "deal_room.customer_message",
        "message_id": int(msg.id),
        "created_at": _utc_iso(msg.created_at),
        "user_id": int(user.id),
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "message": body,
        "sender_type": sender_type,
        "vin": msg.vin,
        "broker_admin_user_id": int(msg.broker_admin_user_id) if msg.broker_admin_user_id is not None else None,
        "ghl_contact_id": ghl_contact_id,
        "ghl_contact_exists": bool(ghl_contact_id),
        "ghl_contact_lookup": ghl_lookup,
    }


def send_broker_customer_message_webhook(payload: Dict[str, Any]) -> None:
    url = (settings.broker_message_webhook_url or "").strip()
    if not url:
        return

    timeout_seconds = max(int(settings.broker_message_webhook_timeout_seconds), 1)
    max_attempts = max(int(settings.broker_message_webhook_max_attempts), 1)
    base_backoff = max(float(settings.broker_message_webhook_retry_backoff_seconds), 0.0)

    headers = {"Content-Type": "application/json"}
    secret = (settings.broker_message_webhook_secret or "").strip()
    if secret:
        headers["X-Webhook-Secret"] = secret

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            logger.info(
                "Broker message webhook delivered message_id=%s attempt=%s",
                payload.get("message_id"),
                attempt,
            )
            return
        except httpx.HTTPError as exc:
            logger.warning(
                "Broker message webhook attempt %s/%s failed for message_id=%s: %s",
                attempt,
                max_attempts,
                payload.get("message_id"),
                exc,
            )
            if attempt >= max_attempts:
                logger.error(
                    "Broker message webhook failed permanently for message_id=%s",
                    payload.get("message_id"),
                )
                return
            if base_backoff > 0:
                time.sleep(base_backoff * (2 ** (attempt - 1)))


def run_broker_customer_message_webhook_task(message_id: int) -> None:
    """
    Deliver Make/Zapier webhook (background). GoHighLevel Deal Room sync runs inline in the
    HTTP handler so it still runs when BROKER_MESSAGE_WEBHOOK_URL is unset and on serverless
    hosts that terminate workers right after the response.
    """
    db = SessionLocal()
    try:
        msg = db.query(BrokerMessage).filter(BrokerMessage.id == int(message_id)).first()
        if not msg:
            logger.warning("Broker message webhook: no row for message_id=%s", message_id)
            return
        sender_type, body = parse_message_from_storage(msg.message_text or "")
        if sender_type != "customer":
            return
        user = db.query(User).filter(User.id == msg.user_id).first()
        if not user:
            logger.warning("Broker message webhook: no user for message_id=%s", message_id)
            return
        if is_broker_message_webhook_enabled():
            payload = build_broker_customer_message_payload(msg, user)
            send_broker_customer_message_webhook(payload)
    except Exception:
        logger.exception("Broker message webhook task failed message_id=%s", message_id)
    finally:
        db.close()
