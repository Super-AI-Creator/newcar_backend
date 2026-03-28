"""Push Deal Room customer messages into GoHighLevel via inbound Live_Chat API shape.

Contact lookup uses GHL_PRIVATE_INTEGRATION_TOKEN (contacts scopes).
If GHL_CONVERSATIONS_PRIVATE_INTEGRATION_TOKEN is set, inbound messages use that
PIT (conversations/message.write); otherwise the main token is used for everything.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.models.user import User
from app.services.ghl_contacts import lookup_ghl_contact_by_email

logger = logging.getLogger(__name__)

GHL_INBOUND_MESSAGE_URL = "https://services.leadconnectorhq.com/conversations/messages/inbound"
GHL_API_VERSION = "2021-07-28"


def _ghl_configured() -> bool:
    return bool((settings.ghl_private_integration_token or "").strip() and (settings.ghl_location_id or "").strip())


def _headers_inbound() -> Dict[str, str]:
    conv = (settings.ghl_conversations_private_integration_token or "").strip()
    token = conv if conv else (settings.ghl_private_integration_token or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": GHL_API_VERSION,
    }


def _digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def normalize_e164_phone(raw: Optional[str]) -> str:
    """Best-effort E.164 for US; returns '' if not usable for SMS."""
    if not raw or not str(raw).strip():
        return ""
    s = str(raw).strip()
    digits = _digits_only(s)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if s.startswith("+") and len(digits) >= 10:
        return "+" + digits
    return ""


def _build_deal_room_body(message_text: str, vin: Optional[str]) -> str:
    lines = [f"Deal Room (customer): {message_text.strip()}"]
    if vin and str(vin).strip():
        lines.append(f"VIN: {str(vin).strip()}")
    text = "\n".join(lines)
    return text[:8000]


def post_ghl_inbound_conversation(*, contact_id: str, text: str, email: str, phone: Optional[str]) -> bool:
    """
    POST /conversations/messages/inbound — Live_Chat style fields.
    The REST API requires contactId (same value as ID in Make).
    """
    location_id = (settings.ghl_location_id or "").strip()
    email_clean = (email or "").strip()
    phone_e164 = normalize_e164_phone(phone)
    from_number = phone_e164 if phone_e164 else (str(phone).strip() if phone and str(phone).strip() else "")

    def build_payload(*, include_location_id: bool) -> Dict[str, Any]:
        p: Dict[str, Any] = {
            "type": "Live_Chat",
            "contactId": contact_id,
            "emailFrom": email_clean,
            "message": text,
        }
        if from_number:
            p["fromNumber"] = from_number
        if include_location_id and location_id:
            p["locationId"] = location_id
        return p

    logged_scope_hint = False
    for include_location_id in (False, True):
        payload = build_payload(include_location_id=include_location_id)
        try:
            with httpx.Client(timeout=25.0) as client:
                response = client.post(GHL_INBOUND_MESSAGE_URL, headers=_headers_inbound(), json=payload)
            if response.status_code < 400:
                logger.info(
                    "GHL inbound Live_Chat sent contact_id=%s location_in_body=%s",
                    contact_id,
                    include_location_id,
                )
                return True
            body = (response.text or "")[:300].replace("\n", " ")
            logger.warning(
                "GHL inbound Live_Chat failed status=%s contact_id=%s location_in_body=%s body=%s",
                response.status_code,
                contact_id,
                include_location_id,
                body or "(empty)",
            )
            if response.status_code == 401 and not logged_scope_hint:
                logged_scope_hint = True
                if (settings.ghl_conversations_private_integration_token or "").strip():
                    logger.warning(
                        "GHL: conversations token needs scope conversations/message.write on "
                        "POST .../conversations/messages/inbound."
                    )
                else:
                    logger.warning(
                        "GHL: add conversations/message.write to the main Private Integration for inbound, "
                        "or set GHL_CONVERSATIONS_PRIVATE_INTEGRATION_TOKEN to a PIT that has it."
                    )
        except httpx.HTTPError as exc:
            logger.warning(
                "GHL inbound Live_Chat HTTP error contact_id=%s location_in_body=%s: %s",
                contact_id,
                include_location_id,
                exc,
            )
        except Exception:
            logger.exception(
                "GHL inbound Live_Chat error contact_id=%s location_in_body=%s",
                contact_id,
                include_location_id,
            )

    return False


def sync_deal_room_customer_message_to_ghl(*, user: User, message_text: str, vin: Optional[str]) -> None:
    """
    If the customer already exists in GHL (by email), post an inbound Live_Chat message.
    Does not create contacts. No-op if GHL token/location missing or feature disabled.
    """
    if not settings.ghl_deal_room_conversation_enabled:
        return
    if not _ghl_configured():
        return

    email = (user.email or "").strip()
    if not email:
        logger.warning("GHL deal room sync skipped: user has no email user_id=%s", user.id)
        return

    body = _build_deal_room_body(message_text, vin)

    contact_id, lookup = lookup_ghl_contact_by_email(email)
    if lookup == "error":
        logger.warning("GHL deal room sync: contact lookup error for %s", email[:48])
        return

    if not contact_id:
        logger.info(
            "GHL deal room sync skipped: no existing contact for %s (inbound only when contact exists)",
            email[:48],
        )
        return

    post_ghl_inbound_conversation(
        contact_id=contact_id,
        text=body,
        email=email,
        phone=user.phone,
    )
