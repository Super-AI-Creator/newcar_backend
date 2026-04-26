import base64
import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    pass


def _send_via_smtp(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def _send_via_resend(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[Iterable[tuple]] = None,
    html_body: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    api_key = settings.resend_api_key
    if not api_key:
        raise EmailDeliveryError("Resend API key is not configured")

    from_addr = (from_email or "").strip() or (settings.resend_from_email or settings.smtp_from_email)
    payload = {
        "from": from_addr,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if reply_to and reply_to.strip():
        payload["reply_to"] = reply_to.strip()
    if html_body:
        payload["html"] = html_body
    if attachments:
        payload["attachments"] = [
            {
                "filename": filename,
                "content": base64.b64encode(content).decode("ascii"),
            }
            for filename, content, _mime_type in attachments
        ]

    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[Iterable[tuple]] = None,
    html_body: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    from_addr = (from_email or "").strip() or settings.smtp_from_email
    msg["From"] = from_addr
    msg["To"] = to_email
    if reply_to and reply_to.strip():
        msg["Reply-To"] = reply_to.strip()
    if html_body:
        msg.set_content(body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(body)

    if attachments:
        for filename, content, mime_type in attachments:
            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    try:
        provider = settings.email_provider.lower()
        if provider == "resend":
            if settings.resend_api_key:
                _send_via_resend(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    attachments=attachments,
                    html_body=html_body,
                    from_email=(from_email or "").strip() or None,
                    reply_to=reply_to,
                )
            else:
                logger.warning(
                    "EMAIL_PROVIDER=resend but RESEND_API_KEY is empty; sending via SMTP "
                    "(SMTP_HOST / SMTP_USERNAME from .env)."
                )
                _send_via_smtp(msg)
        elif provider == "smtp":
            _send_via_smtp(msg)
        else:
            if settings.resend_api_key:
                _send_via_resend(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    attachments=attachments,
                    html_body=html_body,
                    from_email=(from_email or "").strip() or None,
                    reply_to=reply_to,
                )
            else:
                _send_via_smtp(msg)
    except (smtplib.SMTPException, OSError, httpx.HTTPError) as exc:
        raise EmailDeliveryError("Failed to deliver email") from exc
