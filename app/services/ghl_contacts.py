"""Optional GoHighLevel (Lead Connector) contact lookup by email and/or phone."""

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


def _digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def _normalize_phone_digits(value: Optional[str]) -> str:
    """Digits only; US numbers often compared on last 10 digits."""
    if not value or not str(value).strip():
        return ""
    return _digits_only(str(value))


def _phones_equivalent(a: str, b: str) -> bool:
    """Match after digit extraction; US-style last-10 if both long enough."""
    da, db = _normalize_phone_digits(a), _normalize_phone_digits(b)
    if not da or not db:
        return False
    if da == db:
        return True
    if len(da) >= 10 and len(db) >= 10:
        return da[-10:] == db[-10:]
    return False


def _extract_contacts(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("contacts"), list):
        return [c for c in data["contacts"] if isinstance(c, dict)]
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("contacts"), list):
        return [c for c in inner["contacts"] if isinstance(c, dict)]
    return []


def _contact_email_matches(contact: Dict[str, Any], target_email: str) -> bool:
    em = _normalize_email(contact.get("email"))
    return bool(target_email) and em == target_email


def _iter_contact_phone_strings(contact: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in ("phone", "phoneNumber", "mobilePhone"):
        v = contact.get(key)
        if v is not None and str(v).strip():
            out.append(str(v).strip())
    adds = contact.get("additionalPhones")
    if isinstance(adds, list):
        for item in adds:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                p = item.get("phone") or item.get("phoneNumber")
                if p is not None and str(p).strip():
                    out.append(str(p).strip())
    return out


def _contact_phone_matches(contact: Dict[str, Any], applicant_digits: str) -> bool:
    if len(applicant_digits) < 7:
        return False
    for s in _iter_contact_phone_strings(contact):
        if _phones_equivalent(s, applicant_digits):
            return True
    return False


def _ghl_search(query: str) -> Tuple[List[Dict[str, Any]], Literal["ok", "error", "not_configured"]]:
    token = (settings.ghl_private_integration_token or "").strip()
    location_id = (settings.ghl_location_id or "").strip()
    if not token or not location_id:
        return [], "not_configured"
    q = (query or "").strip()
    if not q:
        return [], "ok"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                GHL_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Version": "2021-07-28",
                },
                json={
                    "locationId": location_id,
                    "pageLimit": 20,
                    "query": q,
                },
            )
            if response.status_code >= 400:
                body = (response.text or "")[:300].replace("\n", " ")
                logger.warning(
                    "GHL contact search failed status=%s query=%s body=%s",
                    response.status_code,
                    q[:32],
                    body or "(empty)",
                )
                if response.status_code == 401 and "not authorized for this scope" in (
                    response.text or ""
                ).lower():
                    logger.warning(
                        "GHL: enable contacts.readonly on the Private Integration for POST /contacts/search; "
                        "contacts.write for POST /contacts/ (create). Use one token with every scope this app uses."
                    )
                return [], "error"
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("GHL contact search HTTP error for query=%s: %s", q[:32], exc)
        return [], "error"
    except Exception:
        logger.exception("GHL contact search failed for query=%s", q[:32])
        return [], "error"
    return _extract_contacts(data), "ok"


def _first_contact_id_matching_email(contacts: List[Dict[str, Any]], target_email: str) -> Optional[str]:
    for c in contacts:
        if _contact_email_matches(c, target_email):
            cid = c.get("id")
            if cid is not None:
                return str(cid)
    return None


def _first_contact_id_matching_phone(contacts: List[Dict[str, Any]], applicant_digits: str) -> Optional[str]:
    for c in contacts:
        if _contact_phone_matches(c, applicant_digits):
            cid = c.get("id")
            if cid is not None:
                return str(cid)
    return None


def lookup_ghl_contact_for_credit_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], LookupStatus]:
    """
    If GHL token + location are configured, find a contact matching applicant **email** or **phone**
    (home_phone, work_phone, then phone / mobile_phone if present). Either match counts as found.
    """
    token = (settings.ghl_private_integration_token or "").strip()
    location_id = (settings.ghl_location_id or "").strip()
    if not token or not location_id:
        return None, "not_configured"

    email_n = _normalize_email(payload.get("email") if isinstance(payload.get("email"), str) else None)
    phone_candidates: List[str] = []
    for key in ("home_phone", "work_phone", "phone", "mobile_phone"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            phone_candidates.append(v.strip())

    if not email_n and not any(_normalize_phone_digits(p) for p in phone_candidates):
        return None, "not_found"

    # 1) Email search + exact email match on results
    if email_n:
        contacts, search_status = _ghl_search(email_n)
        if search_status == "error":
            return None, "error"
        if search_status == "not_configured":
            return None, "not_configured"
        cid = _first_contact_id_matching_email(contacts, email_n)
        if cid:
            return cid, "found"

    # 2) Phone search (each number we have) + digit match on results
    for raw_phone in phone_candidates:
        digits = _normalize_phone_digits(raw_phone)
        if len(digits) < 7:
            continue
        query = digits if len(digits) <= 15 else digits[-10:]
        contacts, search_status = _ghl_search(query)
        if search_status == "error":
            return None, "error"
        if search_status == "not_configured":
            return None, "not_configured"
        cid = _first_contact_id_matching_phone(contacts, digits)
        if cid:
            return cid, "found"

    return None, "not_found"


def lookup_ghl_contact_by_email(applicant_email: Optional[str]) -> Tuple[Optional[str], LookupStatus]:
    """Backward-compatible wrapper: email-only lookup."""
    payload: Dict[str, Any] = {}
    if applicant_email:
        payload["email"] = applicant_email
    return lookup_ghl_contact_for_credit_payload(payload)
