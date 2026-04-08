import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.email import EmailDeliveryError, send_email
from app.models.cu_demo_contact import CuDemoContact

logger = logging.getLogger(__name__)


def send_cu_demo_contact_email_task(contact_id: int) -> None:
    """Background task: load row and email notify address."""
    db: Session = SessionLocal()
    try:
        row = db.query(CuDemoContact).filter(CuDemoContact.id == contact_id).first()
        if not row:
            logger.warning("cu_demo_contact id=%s not found for email", contact_id)
            return
        _send_email_for_row(row)
    finally:
        db.close()


def _send_email_for_row(row: CuDemoContact) -> None:
    to = (settings.cu_demo_contact_notify_email or "chris@carscu.com").strip()
    if not to:
        logger.warning("cu_demo_contact_notify_email empty; skipping email for id=%s", row.id)
        return
    subject = f"[CU Platform] Demo request — {row.cu_name}"
    lines = [
        "New demo / contact submission from the Credit Union marketing site.",
        "",
        f"Name: {row.first_name} {row.last_name}",
        f"Credit union: {row.cu_name}",
        f"Email: {row.email}",
        f"Phone: {row.phone or '—'}",
        "",
        "Message:",
        (row.message or "—").strip(),
        "",
        f"Submission id: {row.id}",
    ]
    body = "\n".join(lines)
    html = "<pre>" + _html_escape(body) + "</pre>"
    try:
        send_email(to_email=to, subject=subject, body=body, html_body=html)
    except EmailDeliveryError:
        logger.exception("Failed to send cu_demo_contact email id=%s", row.id)


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
