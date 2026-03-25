"""Optional GoHighLevel (Lead Connector) contact lookup by email."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GHL_SEARCH_URL = "https://services.leadconnectorhq.com/contacts/search"
LookupStatus = Literal["found", "not_found", "not_configured", "error"]


def _normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _extract_contacts(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("contacts"), list):
        return [c for c in data["contacts"] if isinstance(c, dict)]
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("contacts"), list):
        return [c for c in inner["contacts"] if isinstance(c, dict)]
    return []


def _contact_email_matches(contact: Dict[str, Any], target: str) -> bool:
    em = _normalize_email(contact.get("email"))
    return bool(target) and em == target


def lookup_ghl_contact_by_email(applicant_email: Optional[str]) -> Tuple[Optional[str], LookupStatus]:
    """
    If GHL token + location are configured, search for a contact with this email.
    Returns (contact_id_or_none, status).
    """
    token = (settings.ghl_private_integration_token or "").strip()
    location_id = (settings.ghl_location_id or "").strip()
    email = _normalize_email(applicant_email)

    if not token or not location_id:
        return None, "not_configured"
    if not email:
        return None, "not_found"

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                GHL_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Version": "2021-07-28",
                },
                json={
                    "locationId": location_id,
                    "pageLimit": 20,
                    "query": email,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("GHL contact search HTTP error for email=%s: %s", email, exc)
        return None, "error"
    except Exception:
        logger.exception("GHL contact search failed for email=%s", email)
        return None, "error"

    contacts = _extract_contacts(data)
    for c in contacts:
        if _contact_email_matches(c, email):
            cid = c.get("id")
            if cid is not None:
                return str(cid), "found"
    # Query may return fuzzy matches; if none match email exactly, treat as not found
    return None, "not_found"
