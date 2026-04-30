from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.credit_union import CuMemberApproval
from app.models.user import User


def resolve_member_scope_user_id(
    db: Session,
    request_user: User,
    member_user_id: Optional[int],
) -> int:
    """Return the effective user id for member-scoped actions.

    - Normal customers can only act as themselves.
    - Credit union users can act on members linked to their CU via approvals.
    - Admin, broker, dealer, or super_admin may optionally pass member_user_id.
    """
    requester_id = int(request_user.id)
    if member_user_id is None:
        return requester_id
    if int(member_user_id) == requester_id:
        return requester_id

    role_value = request_user.role.value if hasattr(request_user.role, "value") else str(request_user.role)
    target_id = int(member_user_id)

    if role_value in {"admin", "broker_admin", "super_admin", "dealer"}:
        return target_id

    if role_value != "credit_union":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    cu_id = getattr(request_user, "credit_union_id", None)
    if cu_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Credit union scope missing.")

    link_exists = (
        db.query(CuMemberApproval.id)
        .filter(
            CuMemberApproval.credit_union_id == int(cu_id),
            CuMemberApproval.user_id == target_id,
        )
        .first()
    )
    target_user = db.query(User).filter(User.id == target_id).first()
    member_assigned_to_cu = (
        target_user is not None
        and getattr(target_user, "credit_union_id", None) is not None
        and int(getattr(target_user, "credit_union_id")) == int(cu_id)
    )
    if not link_exists and not member_assigned_to_cu:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member is not linked to this credit union.")

    return target_id
