"""
Optional SMS sending (e.g. Twilio). If not configured, send_sms no-ops and returns False.
"""
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_sms(to_phone: str, body: str) -> bool:
    to_phone = (to_phone or "").strip()
    if not to_phone:
        return False
    body = (body or "").strip()
    if not body:
        return False
    if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from_phone]):
        logger.info("SMS not configured (Twilio env missing). Would send to %s: %s", to_phone[:6] + "***", body[:50] + "...")
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            body=body,
            from_=settings.twilio_from_phone,
            to=to_phone,
        )
        return True
    except Exception as exc:
        logger.exception("SMS send failed: %s", exc)
        return False
