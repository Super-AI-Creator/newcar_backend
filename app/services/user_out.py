from sqlalchemy.orm import Session

from app.models.credit_union import CreditUnion, CuMemberApproval
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserOut


def _credit_union_for_member(db: Session, user: User) -> CreditUnion | None:
    """Resolve CU from `users.credit_union_id`, or from a linked approval if missing."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != UserRole.customer.value:
        if not user.credit_union_id:
            return None
        return db.query(CreditUnion).filter(CreditUnion.id == user.credit_union_id).first()

    if user.credit_union_id:
        cu = db.query(CreditUnion).filter(CreditUnion.id == user.credit_union_id).first()
        if cu:
            return cu

    appr = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.user_id == user.id)
        .order_by(CuMemberApproval.updated_at.desc())
        .first()
    )
    if not appr:
        return None
    return db.query(CreditUnion).filter(CreditUnion.id == appr.credit_union_id).first()


def build_user_out(db: Session, user: User) -> UserOut:
    base = UserOut.model_validate(user)
    cu = _credit_union_for_member(db, user)
    if not cu:
        return base.model_copy(update={"credit_union_name": None, "credit_union_slug": None})
    return base.model_copy(update={"credit_union_name": cu.name, "credit_union_slug": cu.slug})
