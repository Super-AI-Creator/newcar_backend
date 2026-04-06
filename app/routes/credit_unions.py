"""
Credit Union management (admin), public white-label config, and pre-approvals.
"""
import re
import secrets
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.credit_union import CreditUnion, CreditUnionLoanProgram, CreditUnionDisclosure, CuMemberApproval
from app.models.enums import UserRole
from app.models.user import User
from app.services.sms import send_sms

router = APIRouter(tags=["credit_unions"])
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _slug(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "-").replace("_", "-")[:64]


# ---------- Schemas ----------
class LoanProgramIn(BaseModel):
    interest_rate: float
    max_term_months: int
    vehicle_type: str = "new"


class DisclosureIn(BaseModel):
    sort_order: int = 0
    text: str


class CreditUnionCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    loan_programs: List[LoanProgramIn] = []
    disclosures: List[DisclosureIn] = []


class CreditUnionUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: Optional[bool] = None
    loan_programs: Optional[List[LoanProgramIn]] = None
    disclosures: Optional[List[DisclosureIn]] = None


def _serialize_cu(cu: CreditUnion, include_relations: bool = True) -> dict:
    out = {
        "id": cu.id,
        "name": cu.name,
        "slug": cu.slug,
        "logo_url": cu.logo_url,
        "banner_url": cu.banner_url,
        "hero_title": cu.hero_title,
        "hero_subtitle": cu.hero_subtitle,
        "phone": cu.phone,
        "address": cu.address,
        "contact_name": cu.contact_name,
        "contact_phone": cu.contact_phone,
        "contact_email": cu.contact_email,
        "signup_token": cu.signup_token,
        "signup_link": f"/creditunions/join?token={cu.signup_token}" if cu.signup_token else None,
        "is_active": cu.is_active,
        "created_at": str(cu.created_at) if cu.created_at else None,
        "updated_at": str(cu.updated_at) if cu.updated_at else None,
    }
    if include_relations:
        out["loan_programs"] = [
            {
                "id": p.id,
                "interest_rate": float(p.interest_rate) if p.interest_rate is not None else None,
                "max_term_months": p.max_term_months,
                "vehicle_type": p.vehicle_type,
            }
            for p in sorted(cu.loan_programs, key=lambda x: (x.vehicle_type, x.max_term_months))
        ]
        out["disclosures"] = [
            {"id": d.id, "sort_order": d.sort_order, "text": d.text}
            for d in sorted(cu.disclosures, key=lambda x: (x.sort_order, x.id))
        ]
    return out


# ---------- Admin: Credit Unions (super_admin) ----------
@router.get("/admin/credit-unions")
def admin_list_credit_unions(
    q: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    query = db.query(CreditUnion)
    if not include_inactive:
        query = query.filter(CreditUnion.is_active == True)
    if q:
        needle = q.strip()
        if needle:
            query = query.filter(
                (CreditUnion.name.ilike(f"%{needle}%"))
                | (CreditUnion.slug.ilike(f"%{needle}%"))
                | (CreditUnion.contact_email.ilike(f"%{needle}%"))
            )
    rows = query.order_by(CreditUnion.name.asc()).limit(limit).all()
    return {"items": [_serialize_cu(r) for r in rows]}


@router.post("/admin/credit-unions")
def admin_create_credit_union(
    payload: CreditUnionCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    slug = (payload.slug or _slug(payload.name)).strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Slug must be lowercase letters, numbers, hyphens only.")
    if db.query(CreditUnion).filter(CreditUnion.slug == slug).first():
        raise HTTPException(status_code=400, detail="A credit union with this slug already exists.")
    cu = CreditUnion(
        name=payload.name.strip(),
        slug=slug,
        logo_url=(payload.logo_url or "").strip() or None,
        banner_url=(payload.banner_url or "").strip() or None,
        hero_title=(payload.hero_title or "").strip() or None,
        hero_subtitle=(payload.hero_subtitle or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        address=(payload.address or "").strip() or None,
        contact_name=(payload.contact_name or "").strip() or None,
        contact_phone=(payload.contact_phone or "").strip() or None,
        contact_email=(payload.contact_email or "").strip() or None,
        signup_token=secrets.token_urlsafe(32),
        is_active=True,
    )
    db.add(cu)
    db.flush()
    for p in payload.loan_programs:
        prog = CreditUnionLoanProgram(
            credit_union_id=cu.id,
            interest_rate=Decimal(str(p.interest_rate)),
            max_term_months=p.max_term_months,
            vehicle_type=(p.vehicle_type or "new").strip().lower() or "new",
        )
        db.add(prog)
    for d in payload.disclosures:
        disc = CreditUnionDisclosure(credit_union_id=cu.id, sort_order=d.sort_order, text=(d.text or "").strip())
        db.add(disc)
    db.commit()
    db.refresh(cu)
    return {"item": _serialize_cu(cu)}


@router.get("/admin/credit-unions/{cu_id}")
def admin_get_credit_union(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    return _serialize_cu(cu)


class AssignStaffBody(BaseModel):
    email: str


@router.post("/admin/credit-unions/{cu_id}/assign-staff")
def admin_assign_credit_union_staff(
    cu_id: int,
    payload: AssignStaffBody,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    email = (payload.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    target = db.query(User).filter(User.email == email).first()
    if not target:
        raise HTTPException(status_code=404, detail=f"No user found with email {email}. They must register first.")
    target.role = UserRole.credit_union
    target.credit_union_id = cu_id
    db.commit()
    return {"ok": True, "message": f"{email} is now Credit Union staff for {cu.name}. They can log in and use the CU dashboard."}


@router.put("/admin/credit-unions/{cu_id}")
def admin_update_credit_union(
    cu_id: int,
    payload: CreditUnionUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    if payload.name is not None:
        cu.name = payload.name.strip()
    if payload.slug is not None:
        slug = payload.slug.strip().lower()
        if not _SLUG_RE.match(slug):
            raise HTTPException(status_code=400, detail="Slug must be lowercase letters, numbers, hyphens only.")
        if db.query(CreditUnion).filter(CreditUnion.slug == slug, CreditUnion.id != cu_id).first():
            raise HTTPException(status_code=400, detail="Another credit union already has this slug.")
        cu.slug = slug
    if payload.logo_url is not None:
        cu.logo_url = (payload.logo_url or "").strip() or None
    if payload.banner_url is not None:
        cu.banner_url = (payload.banner_url or "").strip() or None
    if payload.hero_title is not None:
        cu.hero_title = (payload.hero_title or "").strip() or None
    if payload.hero_subtitle is not None:
        cu.hero_subtitle = (payload.hero_subtitle or "").strip() or None
    if payload.phone is not None:
        cu.phone = (payload.phone or "").strip() or None
    if payload.address is not None:
        cu.address = (payload.address or "").strip() or None
    if payload.contact_name is not None:
        cu.contact_name = (payload.contact_name or "").strip() or None
    if payload.contact_phone is not None:
        cu.contact_phone = (payload.contact_phone or "").strip() or None
    if payload.contact_email is not None:
        cu.contact_email = (payload.contact_email or "").strip() or None
    if payload.is_active is not None:
        cu.is_active = bool(payload.is_active)
    if payload.loan_programs is not None:
        db.query(CreditUnionLoanProgram).filter(CreditUnionLoanProgram.credit_union_id == cu_id).delete()
        for p in payload.loan_programs:
            prog = CreditUnionLoanProgram(
                credit_union_id=cu.id,
                interest_rate=Decimal(str(p.interest_rate)),
                max_term_months=p.max_term_months,
                vehicle_type=(p.vehicle_type or "new").strip().lower() or "new",
            )
            db.add(prog)
    if payload.disclosures is not None:
        db.query(CreditUnionDisclosure).filter(CreditUnionDisclosure.credit_union_id == cu_id).delete()
        for d in payload.disclosures:
            disc = CreditUnionDisclosure(credit_union_id=cu.id, sort_order=d.sort_order, text=(d.text or "").strip())
            db.add(disc)
    db.commit()
    db.refresh(cu)
    return {"item": _serialize_cu(cu)}


@router.delete("/admin/credit-unions/{cu_id}")
def admin_delete_credit_union(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    db.delete(cu)
    db.commit()
    return {"deleted": True, "id": cu_id}


# ---------- Public: White-label config (no auth) ----------
@router.get("/credit-unions/by-slug/{slug}")
def get_credit_union_by_slug(slug: str, db: Session = Depends(get_db)):
    cu = db.query(CreditUnion).filter(CreditUnion.slug == slug, CreditUnion.is_active == True).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    return _serialize_cu(cu)


@router.get("/credit-unions/by-token")
def get_credit_union_by_signup_token(token: str = Query(..., alias="token"), db: Session = Depends(get_db)):
    cu = db.query(CreditUnion).filter(CreditUnion.signup_token == token, CreditUnion.is_active == True).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Invalid or expired signup link.")
    return _serialize_cu(cu)


# ---------- Pre-approvals ----------
class ApprovalCreate(BaseModel):
    loan_amount: float
    term_months: int
    special_notes: Optional[str] = None
    approval_code: Optional[str] = None
    member_phone: Optional[str] = None
    member_email: Optional[str] = None


class ApprovalUpdate(BaseModel):
    status: Optional[str] = None


_ALLOWED_APPROVAL_STATUSES = {
    "pending",
    "active",
    "funded",
    "lost",
    "canceled",
    "claimed",
}

def _can_manage_cu(user: User, cu_id: int) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "super_admin":
        return True
    if role == "credit_union" and getattr(user, "credit_union_id", None) == cu_id:
        return True
    return False


def _serialize_approval(a: CuMemberApproval, include_cu_name: bool = False) -> dict:
    out = {
        "id": a.id,
        "credit_union_id": a.credit_union_id,
        "user_id": a.user_id,
        "loan_amount": float(a.loan_amount) if a.loan_amount is not None else None,
        "term_months": a.term_months,
        "special_notes": a.special_notes,
        "approval_code": a.approval_code,
        "member_phone": a.member_phone,
        "member_email": a.member_email,
        "status": a.status,
        "created_at": str(a.created_at) if a.created_at else None,
        "updated_at": str(a.updated_at) if a.updated_at else None,
    }
    if include_cu_name and a.credit_union_id:
        cu = a.credit_union
        out["credit_union_name"] = cu.name if cu else None
    return out


@router.post("/admin/credit-unions/{cu_id}/approvals")
def create_approval(
    cu_id: int,
    payload: ApprovalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    if not _can_manage_cu(user, cu_id):
        raise HTTPException(status_code=403, detail="Not allowed to create approvals for this credit union.")
    code = (payload.approval_code or "").strip() or secrets.token_urlsafe(12).upper()[:16]
    if db.query(CuMemberApproval).filter(CuMemberApproval.approval_code == code).first():
        code = secrets.token_urlsafe(12).upper()[:16]
    approval = CuMemberApproval(
        credit_union_id=cu_id,
        loan_amount=Decimal(str(payload.loan_amount)),
        term_months=payload.term_months,
        special_notes=(payload.special_notes or "").strip() or None,
        approval_code=code,
        member_phone=(payload.member_phone or "").strip() or None,
        member_email=(payload.member_email or "").strip() or None,
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    base = (settings.frontend_base_url or "").rstrip("/")
    claim_url = f"{base}/approvals/{approval.approval_code}"
    join_url = f"{base}/creditunions/join?token={cu.signup_token}&approval={approval.approval_code}"
    sms_sent = False
    if approval.member_phone:
        body = f"{cu.name}: You have a pre-approved auto loan. Create an account or log in to view: {claim_url}"
        sms_sent = send_sms(approval.member_phone, body)
    return {
        "item": _serialize_approval(approval),
        "approval_code": approval.approval_code,
        "claim_url": claim_url,
        "join_url": join_url,
        "sms_sent": sms_sent,
    }


@router.get("/approvals/mine")
def list_my_approvals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    query = db.query(CuMemberApproval)
    if role in ("super_admin", "credit_union"):
        if role == "credit_union" and user.credit_union_id:
            query = query.filter(CuMemberApproval.credit_union_id == user.credit_union_id)
        rows = query.order_by(CuMemberApproval.created_at.desc()).limit(100).all()
    else:
        query = query.filter(
            (CuMemberApproval.user_id == user.id) | (CuMemberApproval.member_email == user.email)
        )
        rows = query.order_by(CuMemberApproval.created_at.desc()).limit(50).all()
    return {"items": [_serialize_approval(r, include_cu_name=True) for r in rows]}


@router.get("/approvals/by-code/{code}")
def get_approval_by_code(code: str, db: Session = Depends(get_db)):
    approval = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.approval_code == code)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == approval.credit_union_id).first()
    base = (settings.frontend_base_url or "").rstrip("/")
    portal_url = None
    if cu and cu.slug and base:
        portal_url = f"{base}/cu/{cu.slug}"
    return {
        **_serialize_approval(approval),
        "credit_union_name": cu.name if cu else None,
        "credit_union_slug": cu.slug if cu else None,
        "credit_union_logo_url": (cu.logo_url or "").strip() or None if cu else None,
        "credit_union_address": (cu.address or "").strip() or None if cu else None,
        "credit_union_phone": (cu.phone or "").strip() or None if cu else None,
        "credit_union_portal_url": portal_url,
        "contact_name": (cu.contact_name or "").strip() or None if cu else None,
        "contact_phone": (cu.contact_phone or "").strip() or None if cu else None,
        "contact_email": (cu.contact_email or "").strip() or None if cu else None,
    }


@router.patch("/admin/credit-unions/{cu_id}/approvals/{approval_id}")
def update_approval_status(
    cu_id: int,
    approval_id: int,
    payload: ApprovalUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage_cu(user, cu_id):
        raise HTTPException(status_code=403, detail="Not allowed to update approvals for this credit union.")
    approval = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.id == approval_id, CuMemberApproval.credit_union_id == cu_id)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if payload.status is not None:
        status = (payload.status or "").strip().lower()
        if status not in _ALLOWED_APPROVAL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {', '.join(sorted(_ALLOWED_APPROVAL_STATUSES))}.",
            )
        approval.status = status
    db.commit()
    db.refresh(approval)
    return {"item": _serialize_approval(approval)}


@router.patch("/approvals/claim/{code}")
def claim_approval(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    approval = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.approval_code == code)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.user_id is not None:
        return {"item": _serialize_approval(approval), "already_claimed": True}
    approval.user_id = user.id
    approval.status = "claimed"
    db.commit()
    db.refresh(approval)
    return {"item": _serialize_approval(approval), "claimed": True}
