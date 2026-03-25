"""Email + Make.com (or any) webhook delivery after a credit application is saved."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.email import EmailDeliveryError, send_email
from app.services.credit_application_format import format_credit_application_html, format_credit_application_plain
from app.services.ghl_contacts import lookup_ghl_contact_by_email

logger = logging.getLogger(__name__)


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def is_credit_webhook_enabled() -> bool:
    return bool((settings.credit_application_webhook_url or "").strip())


def send_credit_application_webhook(
    *,
    application_id: int,
    source: str,
    vin: Optional[str],
    payload_json: Dict[str, Any],
    created_at: Optional[datetime],
    ghl_contact_id: Optional[str],
    ghl_contact_lookup: str,
) -> None:
    url = (settings.credit_application_webhook_url or "").strip()
    if not url:
        return

    timeout_seconds = max(int(settings.credit_application_webhook_timeout_seconds), 1)
    max_attempts = max(int(settings.credit_application_webhook_max_attempts), 1)
    base_backoff = max(float(settings.credit_application_webhook_retry_backoff_seconds), 0.0)

    # Readable copies for Make / GoHighLevel (masked); full structured data in payload_json for field mapping.
    plain_masked = format_credit_application_plain(payload_json, mask_sensitive=True)
    html_masked = format_credit_application_html(payload_json, mask_sensitive=True)

    body: Dict[str, Any] = {
        "event": "credit_application.submitted",
        "application_id": int(application_id),
        "created_at": _utc_iso(created_at),
        "source": source,
        "vin": vin,
        "formatted_plain": plain_masked,
        "formatted_html": html_masked,
        "payload": payload_json,
        "ghl_contact_id": ghl_contact_id,
        "ghl_contact_exists": bool(ghl_contact_id),
        "ghl_contact_lookup": ghl_contact_lookup,
    }

    headers = {"Content-Type": "application/json"}
    secret = (settings.credit_application_webhook_secret or "").strip()
    if secret:
        headers["X-Webhook-Secret"] = secret

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, json=body, headers=headers)
                response.raise_for_status()
            logger.info("Credit application webhook delivered id=%s attempt=%s", application_id, attempt)
            return
        except httpx.HTTPError as exc:
            logger.warning(
                "Credit application webhook attempt %s/%s failed for id=%s: %s",
                attempt,
                max_attempts,
                application_id,
                exc,
            )
            if attempt >= max_attempts:
                logger.error("Credit application webhook failed permanently for id=%s", application_id)
                return
            if base_backoff > 0:
                time.sleep(base_backoff * (2 ** (attempt - 1)))


def send_credit_application_email(
    *,
    application_id: int,
    source: str,
    vin: Optional[str],
    payload_json: Dict[str, Any],
) -> None:
    if not settings.credit_application_email_enabled:
        return

    to = (settings.credit_application_notify_email or settings.broker_email or "").strip()
    if not to:
        logger.warning("Credit application email skipped: no broker_email / credit_application_notify_email")
        return

    name = " ".join(
        [
            str(payload_json.get("first_name") or "").strip(),
            str(payload_json.get("last_name") or "").strip(),
        ]
    ).strip() or "Applicant"

    subject = f"Credit Application #{application_id} — {name}"
    if vin:
        subject = f"{subject} (VIN {vin})"

    plain = format_credit_application_plain(payload_json, mask_sensitive=True)
    header = f"Application ID: {application_id}\nSource: {source}\n"
    if vin:
        header += f"VIN: {vin}\n"
    header += "\n"

    html_inner = format_credit_application_html(payload_json, mask_sensitive=True)
    html_wrap = (
        f'<p style="font-family:system-ui,sans-serif;font-size:14px;color:#333;">'
        f"<strong>Application ID:</strong> {application_id}<br/>"
        f"<strong>Source:</strong> {source}<br/>"
        + (f"<strong>VIN:</strong> {vin}<br/>" if vin else "")
        + "</p>"
        + html_inner
    )

    try:
        send_email(to_email=to, subject=subject, body=header + plain, html_body=html_wrap)
    except EmailDeliveryError:
        logger.exception("Credit application email failed for id=%s", application_id)


def send_credit_application_ghl_fallback_email(
    *,
    application_id: int,
    source: str,
    vin: Optional[str],
    payload_json: Dict[str, Any],
) -> None:
    """Email formatted application when applicant has no matching GHL contact (broker ops inbox)."""
    if not settings.credit_application_email_enabled:
        return
    to = (settings.credit_application_ghl_fallback_email or "").strip()
    if not to:
        return

    name = " ".join(
        [
            str(payload_json.get("first_name") or "").strip(),
            str(payload_json.get("last_name") or "").strip(),
        ]
    ).strip() or "Applicant"
    applicant_email = str(payload_json.get("email") or "").strip()

    subject = f"[Credit app — not in GHL] #{application_id} — {name}"
    if applicant_email:
        subject = f"{subject} ({applicant_email})"
    if vin:
        subject = f"{subject} VIN {vin}"

    plain = format_credit_application_plain(payload_json, mask_sensitive=True)
    header = (
        f"No existing GoHighLevel contact matched this email before submit.\n"
        f"Application ID: {application_id}\nSource: {source}\nApplicant email: {applicant_email or '—'}\n"
    )
    if vin:
        header += f"VIN: {vin}\n"
    header += "\n"

    html_inner = format_credit_application_html(payload_json, mask_sensitive=True)
    html_wrap = (
        f'<p style="font-family:system-ui,sans-serif;font-size:14px;color:#333;">'
        f"<strong>No GHL contact match</strong> for applicant email.<br/>"
        f"<strong>Application ID:</strong> {application_id}<br/>"
        f"<strong>Source:</strong> {source}<br/>"
        f"<strong>Applicant email:</strong> {applicant_email or '—'}<br/>"
        + (f"<strong>VIN:</strong> {vin}<br/>" if vin else "")
        + "</p>"
        + html_inner
    )

    try:
        send_email(to_email=to, subject=subject, body=header + plain, html_body=html_wrap)
    except EmailDeliveryError:
        logger.exception("Credit application GHL fallback email failed for id=%s", application_id)


def notify_credit_application_submitted(
    *,
    application_id: int,
    source: str,
    vin: Optional[str],
    payload_json: Dict[str, Any],
    created_at: Optional[datetime],
) -> None:
    """Fire-and-forget style calls from request handlers; failures are logged only.

    Client flow (when GHL token + location are configured):
    - Contact exists in GHL → send Make webhook only (for note / automation on existing contact).
    - Contact not in GHL → email CREDIT_APPLICATION_GHL_FALLBACK_EMAIL only; do **not** call webhook.

    If GHL lookup is not configured or errors, we still send the webhook (legacy behavior) so Make is not dead.
    """
    applicant_email = payload_json.get("email")
    ghl_id, ghl_status = lookup_ghl_contact_by_email(applicant_email if isinstance(applicant_email, str) else None)

    try:
        send_credit_application_email(
            application_id=application_id,
            source=source,
            vin=vin,
            payload_json=payload_json,
        )
    except Exception:
        logger.exception("Unexpected error sending credit application email id=%s", application_id)

    if ghl_status == "found":
        try:
            send_credit_application_webhook(
                application_id=application_id,
                source=source,
                vin=vin,
                payload_json=payload_json,
                created_at=created_at,
                ghl_contact_id=ghl_id,
                ghl_contact_lookup=ghl_status,
            )
        except Exception:
            logger.exception("Unexpected error sending credit application webhook id=%s", application_id)
        return

    if ghl_status == "not_found":
        if (settings.credit_application_ghl_fallback_email or "").strip():
            try:
                send_credit_application_ghl_fallback_email(
                    application_id=application_id,
                    source=source,
                    vin=vin,
                    payload_json=payload_json,
                )
            except Exception:
                logger.exception("Unexpected error sending credit GHL fallback email id=%s", application_id)
        # No webhook — new applicant is handled via email only.
        return

    # not_configured or error: cannot know if contact exists; keep webhook for backward compatibility.
    try:
        send_credit_application_webhook(
            application_id=application_id,
            source=source,
            vin=vin,
            payload_json=payload_json,
            created_at=created_at,
            ghl_contact_id=ghl_id,
            ghl_contact_lookup=ghl_status,
        )
    except Exception:
        logger.exception("Unexpected error sending credit application webhook id=%s", application_id)
