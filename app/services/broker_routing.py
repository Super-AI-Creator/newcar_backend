from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.broker_message import BrokerMessage
from app.models.enums import UserRole
from app.models.user import User


def select_next_broker_admin_user_id(db: Session) -> int | None:
    """
    Round-robin assignment by least-recently-assigned broker.
    Brokers with no prior assignments are selected first.
    """
    rows = (
        db.query(
            User.id,
            func.max(BrokerMessage.created_at).label("last_assigned_at"),
        )
        .outerjoin(BrokerMessage, BrokerMessage.broker_admin_user_id == User.id)
        .filter(User.role == UserRole.broker_admin)
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
