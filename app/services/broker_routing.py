from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.auth_realm import AUTH_REALM_CARSCU
from app.core.config import settings
from app.models.broker_message import BrokerMessage
from app.models.enums import UserRole
from app.models.user import User


def select_next_broker_admin_user_id(db: Session) -> int | None:
    """
    When BROKER_SINGLE_ASSIGN_EMAIL is set and matches a broker_admin user, always assign to them
    (default deal-room routing, e.g. Power Auto Buying / chris@carscu.com).

    Otherwise: round-robin by least-recently-assigned broker_admin.
    """
    single = (settings.broker_single_assign_email or "").strip().lower()
    if single:
        fixed = (
            db.query(User.id)
            .filter(
                func.lower(func.trim(User.email)) == single,
                User.role == UserRole.broker_admin,
                User.auth_realm == AUTH_REALM_CARSCU,
            )
            .first()
        )
        if fixed:
            return int(fixed[0])

    rows = (
        db.query(
            User.id,
            func.max(BrokerMessage.created_at).label("last_assigned_at"),
        )
        .outerjoin(BrokerMessage, BrokerMessage.broker_admin_user_id == User.id)
        .filter(User.role == UserRole.broker_admin, User.auth_realm == AUTH_REALM_CARSCU)
        .group_by(User.id)
        .order_by(
            case((func.max(BrokerMessage.created_at).is_(None), 0), else_=1).asc(),
            func.max(BrokerMessage.created_at).asc(),
            User.id.asc(),
        )
        .all()
    )
    if not rows:
        return None
    return int(rows[0][0])
