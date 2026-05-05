"""
Credit Union management (admin), public white-label config, and pre-approvals.
"""
import re
import secrets
import string
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_realm import AUTH_REALM_CARSCU
from app.core.config import settings
from app.core.email import EmailDeliveryError, send_email
from app.core.deps import get_current_user, get_db, require_role
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.broker_message import BrokerMessage
from app.models.credit_union import (
    CreditUnion,
    CreditUnionLoanProgram,
    CreditUnionDisclosure,
    CreditUnionMemberInvite,
    CuMemberApproval,
)
from app.models.deal import Deal
from app.models.document_submission import DocumentSubmission
from app.models.enums import UserRole
from app.models.favorite import Favorite
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import UserOut
from app.services.cu_member_scope import resolve_member_scope_user_id
from app.services.sms import send_sms
from app.services.user_out import _credit_union_for_member

router = APIRouter(tags=["credit_unions"])
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Internal reference / approval lookup: letters, digits, hyphen, underscore (1–64 chars)
_APPROVAL_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
    testimonial_image_url: Optional[str] = None
    testimonial_text: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    loan_programs: List[LoanProgramIn] = []
    disclosures: List[DisclosureIn] = []


class MemberInviteCreate(BaseModel):
    """Optional email locks signup to that address for this one-time link."""

    invited_email: Optional[str] = None
    invited_name: Optional[str] = None
    invited_phone: Optional[str] = None

    @field_validator("invited_email", mode="before")
    @classmethod
    def normalize_invited_email(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            return s or None
        return None

    @field_validator("invited_name", mode="before")
    @classmethod
    def normalize_invited_name(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s[:255] or None
        return None

    @field_validator("invited_phone", mode="before")
    @classmethod
    def normalize_invited_phone(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s[:50] or None
        return None


class CreditUnionUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    logo_url: Optional[str] = None
    testimonial_image_url: Optional[str] = None
    testimonial_text: Optional[str] = None
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


def _serialize_cu(
    cu: CreditUnion,
    include_relations: bool = True,
    include_admin_internal: bool = False,
) -> dict:
    out = {
        "id": cu.id,
        "name": cu.name,
        "slug": cu.slug,
        "logo_url": cu.logo_url,
        "banner_url": cu.banner_url,
        "hero_title": cu.hero_title,
        "hero_subtitle": cu.hero_subtitle,
        "testimonial_image_url": cu.testimonial_image_url,
        "testimonial_text": cu.testimonial_text,
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
    if include_admin_internal:
        out["primary_staff_user_id"] = getattr(cu, "primary_staff_user_id", None)
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


def _portal_base_url() -> str:
    base = (settings.cu_portal_base_url or settings.frontend_base_url or "").rstrip("/")
    low = base.lower()
    # Safety net for deployments still carrying legacy frontend URL env values.
    if "newcar-frontend.vercel.app" in low:
        return "https://carscu.com"
    return base


def _platform_member_site_base_url() -> str:
    """Main member site base for invite/join links; prefer CU portal domain."""
    base = (settings.cu_portal_base_url or settings.frontend_base_url or "").rstrip("/")
    low = base.lower()
    if "newcar-frontend.vercel.app" in low:
        return "https://carscu.com"
    return base


def _attach_primary_staff_summary_to_admin_cu_items(db: Session, rows: list, items: List[dict]) -> None:
    """Mutates each item dict with primary_staff_email / primary_staff_name for the admin directory."""
    if not rows:
        return
    cu_ids = [int(cu.id) for cu in rows]
    staff_rows = (
        db.query(User)
        .filter(
            User.credit_union_id.in_(cu_ids),
            User.role == UserRole.credit_union,
            User.auth_realm == AUTH_REALM_CARSCU,
        )
        .order_by(User.credit_union_id.asc(), User.id.asc())
        .all()
    )
    first_staff_by_cu: dict[int, User] = {}
    for u in staff_rows:
        cid = int(u.credit_union_id)
        if cid not in first_staff_by_cu:
            first_staff_by_cu[cid] = u

    primary_ids = [int(getattr(cu, "primary_staff_user_id", None) or 0) for cu in rows]
    pid_set = {pid for pid in primary_ids if pid > 0}
    users_by_id: dict[int, User] = {}
    if pid_set:
        for u in db.query(User).filter(User.id.in_(pid_set)).all():
            users_by_id[int(u.id)] = u

    for item, cu in zip(items, rows):
        cid = int(cu.id)
        staff_user: Optional[User] = None
        pid = getattr(cu, "primary_staff_user_id", None)
        if pid:
            u = users_by_id.get(int(pid))
            if (
                u
                and u.role == UserRole.credit_union
                and int(u.credit_union_id or 0) == cid
            ):
                staff_user = u
        if staff_user is None:
            staff_user = first_staff_by_cu.get(cid)
        item["primary_staff_email"] = staff_user.email if staff_user else None
        item["primary_staff_name"] = (staff_user.name if staff_user else None) or None


# ---------- Admin: Credit Unions (super_admin) ----------
@router.get("/admin/credit-unions")
def admin_list_credit_unions(
    q: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    include_primary_staff: bool = Query(True),
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
    items = [_serialize_cu(r, include_admin_internal=True) for r in rows]
    if include_primary_staff:
        _attach_primary_staff_summary_to_admin_cu_items(db, rows, items)
    return {"items": items}


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
        banner_url=None,
        testimonial_image_url=(payload.testimonial_image_url or "").strip() or None,
        testimonial_text=(payload.testimonial_text or "").strip() or None,
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
    return {"item": _serialize_cu(cu, include_admin_internal=True)}


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
    return _serialize_cu(cu, include_admin_internal=True)


class AssignStaffBody(BaseModel):
    email: str
    """Display name — required only when creating a new user (email not yet registered)."""
    name: Optional[str] = None
    """Temporary password — required only when creating a new user (min 8 characters)."""
    password: Optional[str] = None


class SetPrimaryStaffBody(BaseModel):
    user_id: int


def _generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _primary_staff_user(db: Session, cu: CreditUnion) -> Optional[User]:
    pid = getattr(cu, "primary_staff_user_id", None)
    if pid:
        u = db.query(User).filter(User.id == pid).first()
        if u and u.role == UserRole.credit_union and int(u.credit_union_id or 0) == int(cu.id):
            return u
    return (
        db.query(User)
        .filter(
            User.credit_union_id == cu.id,
            User.role == UserRole.credit_union,
            User.auth_realm == AUTH_REALM_CARSCU,
        )
        .order_by(User.id.asc())
        .first()
    )


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
    target = db.query(User).filter(User.email == email, User.auth_realm == AUTH_REALM_CARSCU).first()
    staff_user: User
    message: str

    if target:
        if target.role == UserRole.super_admin:
            raise HTTPException(
                status_code=400,
                detail="That account is a platform super admin and cannot be switched to credit union staff.",
            )
        target.role = UserRole.credit_union
        target.credit_union_id = cu_id
        target.auth_realm = AUTH_REALM_CARSCU
        staff_user = target
        message = f"{email} is now Credit Union staff for {cu.name}. They can log in at /login and open the CU dashboard."
    else:
        pwd = (payload.password or "").strip()
        name = (payload.name or "").strip()
        if len(pwd) < 8:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No account exists with that email yet. Either have them register at /register first, "
                    "or enter Display name + Temporary password (8+ characters) below to create their staff login now."
                ),
            )
        if not name:
            raise HTTPException(status_code=400, detail="Display name is required when creating a new staff user.")

        staff_user = User(
            email=email,
            name=name,
            role=UserRole.credit_union,
            password_hash=hash_password(pwd),
            credit_union_id=cu_id,
            phone=None,
            auth_realm=AUTH_REALM_CARSCU,
            is_email_verified=True,
            is_phone_verified=False,
        )
        db.add(staff_user)
        message = f"Created staff login for {email} on {cu.name}. They can sign in at /login and should change their password after first login."

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create user (email may already be in use).") from None

    if getattr(cu, "primary_staff_user_id", None) is None:
        cu.primary_staff_user_id = staff_user.id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not save staff assignment.") from None

    return {"ok": True, "message": message}


@router.get("/admin/credit-unions/{cu_id}/primary-staff-summary")
def admin_primary_staff_summary(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    staff = _primary_staff_user(db, cu)
    staff_rows = (
        db.query(User)
        .filter(
            User.credit_union_id == cu_id,
            User.role == UserRole.credit_union,
            User.auth_realm == AUTH_REALM_CARSCU,
        )
        .order_by(User.id.asc())
        .all()
    )
    return {
        "primary_staff_user_id": getattr(cu, "primary_staff_user_id", None),
        "primary": (
            {
                "user_id": staff.id,
                "email": staff.email,
                "name": staff.name,
                "has_password": bool(staff.password_hash),
            }
            if staff
            else None
        ),
        "all_staff": [
            {
                "user_id": u.id,
                "email": u.email,
                "name": u.name,
                "is_primary": bool(staff and u.id == staff.id),
            }
            for u in staff_rows
        ],
    }


@router.post("/admin/credit-unions/{cu_id}/primary-staff")
def admin_set_primary_staff(
    cu_id: int,
    payload: SetPrimaryStaffBody,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    staff = (
        db.query(User)
        .filter(
            User.id == payload.user_id,
            User.credit_union_id == cu_id,
            User.role == UserRole.credit_union,
            User.auth_realm == AUTH_REALM_CARSCU,
        )
        .first()
    )
    if not staff:
        raise HTTPException(status_code=400, detail="That user is not credit union staff for this organization.")
    cu.primary_staff_user_id = staff.id
    db.commit()
    return {"ok": True, "message": f"Primary staff login is now {staff.email}."}


@router.post("/admin/credit-unions/{cu_id}/reset-primary-staff-password")
def admin_reset_primary_staff_password(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    staff = _primary_staff_user(db, cu)
    if not staff:
        raise HTTPException(
            status_code=400,
            detail="No primary CU staff user. Assign or create staff first, then try again.",
        )
    plain = _generate_temp_password(16)
    staff.password_hash = hash_password(plain)
    db.commit()
    return {
        "ok": True,
        "temporary_password": plain,
        "email": staff.email,
        "message": "Temporary password generated. Copy it now — it will not be shown again.",
    }


@router.post("/admin/credit-unions/{cu_id}/impersonate-staff", response_model=TokenResponse)
def admin_impersonate_credit_union_staff(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    staff = _primary_staff_user(db, cu)
    if not staff:
        raise HTTPException(
            status_code=400,
            detail="No CU staff to impersonate. Assign or create a staff user for this credit union first.",
        )
    sub = str(staff.id)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    return TokenResponse(access_token=access, refresh_token=refresh)


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
    cu.banner_url = None
    if payload.testimonial_image_url is not None:
        cu.testimonial_image_url = (payload.testimonial_image_url or "").strip() or None
    if payload.testimonial_text is not None:
        cu.testimonial_text = (payload.testimonial_text or "").strip() or None
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
    return {"item": _serialize_cu(cu, include_admin_internal=True)}


@router.delete("/admin/credit-unions/{cu_id}")
@router.post("/admin/credit-unions/{cu_id}/delete")
def admin_delete_credit_union(
    cu_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    # Capture CU staff before clearing credit_union_id (role cleanup avoids orphaned credit_union users).
    cu_staff_ids = [
        row[0]
        for row in db.query(User.id).filter(User.credit_union_id == cu_id, User.role == UserRole.credit_union).all()
    ]
    # Make deletion resilient across older schemas where FK ON DELETE rules may be missing.
    db.query(User).filter(User.credit_union_id == cu_id).update({User.credit_union_id: None}, synchronize_session=False)
    if cu_staff_ids:
        db.query(User).filter(User.id.in_(cu_staff_ids)).update({User.role: UserRole.customer}, synchronize_session=False)
    db.query(Deal).filter(Deal.credit_union_id == cu_id).update({Deal.credit_union_id: None}, synchronize_session=False)
    # Deals may still point at approvals for this CU; clear before deleting approvals.
    approval_id_rows = [
        row[0]
        for row in db.query(CuMemberApproval.id).filter(CuMemberApproval.credit_union_id == cu_id).all()
    ]
    if approval_id_rows:
        db.query(Deal).filter(Deal.cu_approval_id.in_(approval_id_rows)).update(
            {Deal.cu_approval_id: None}, synchronize_session=False
        )
    db.query(CreditUnionLoanProgram).filter(CreditUnionLoanProgram.credit_union_id == cu_id).delete(synchronize_session=False)
    db.query(CreditUnionDisclosure).filter(CreditUnionDisclosure.credit_union_id == cu_id).delete(synchronize_session=False)
    db.query(CreditUnionMemberInvite).filter(CreditUnionMemberInvite.credit_union_id == cu_id).delete(synchronize_session=False)
    db.query(CuMemberApproval).filter(CuMemberApproval.credit_union_id == cu_id).delete(synchronize_session=False)
    db.flush()
    # Bulk delete avoids ORM identity-map edge cases after heavy FK cleanup.
    removed = db.query(CreditUnion).filter(CreditUnion.id == cu_id).delete(synchronize_session=False)
    if removed != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Credit union could not be deleted (row missing or blocked).")
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        hint = ""
        if getattr(e, "orig", None) is not None and getattr(e.orig, "args", None):
            hint = f" ({e.orig.args[0]})" if e.orig.args else ""
        raise HTTPException(
            status_code=409,
            detail=f"Could not delete credit union because related records still reference it.{hint}",
        )
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


@router.get("/credit-unions/by-invite")
def get_credit_union_by_member_invite(invite: str = Query(..., alias="invite"), db: Session = Depends(get_db)):
    """Public: resolve an unused personal member invite to the parent credit union (for join/register preview)."""
    raw = (invite or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Invalid invitation.")
    inv = (
        db.query(CreditUnionMemberInvite)
        .filter(
            CreditUnionMemberInvite.token == raw,
            CreditUnionMemberInvite.used_at.is_(None),
        )
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Invalid or already used invitation link.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == inv.credit_union_id, CreditUnion.is_active == True).first()
    if not cu:
        raise HTTPException(status_code=404, detail="This invitation is no longer valid.")
    out = _serialize_cu(cu)
    out["is_personal_invite"] = True
    out["invited_email"] = inv.invited_email
    out["invited_name"] = inv.invited_name
    out["invited_phone"] = inv.invited_phone
    return out


@router.get("/credit-unions/for-member")
def get_credit_union_for_logged_in_member(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Logged-in member: return their credit union's public config (slug, name, logo, etc.).
    Used by the marketplace header when the client session is missing `credit_union_slug` on `/me`.
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != UserRole.customer.value:
        raise HTTPException(status_code=403, detail="Members only.")
    cu = _credit_union_for_member(db, user)
    if not cu:
        raise HTTPException(status_code=404, detail="No credit union linked to this account.")
    return _serialize_cu(cu)


@router.get("/credit-unions/mine")
def get_my_credit_union_staff_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Signup link and token for the logged-in credit union staff member's organization (not for platform admins)."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == int(cu_id)).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    rel = f"/creditunions/join?token={cu.signup_token}" if cu.signup_token else None
    base = _portal_base_url()
    signup_link = f"{base}{rel}" if (base and rel) else rel
    return {
        "name": cu.name,
        "slug": cu.slug,
        "signup_token": cu.signup_token,
        "signup_link": signup_link,
    }


@router.get("/credit-unions/mine/members")
def list_my_credit_union_members(
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Credit union staff: list customer accounts assigned to their own credit union."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == int(cu_id)).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    rows = (
        db.query(User)
        .filter(
            User.credit_union_id == int(cu_id),
            User.role == UserRole.customer,
        )
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit)
        .all()
    )
    out: list[UserOut] = []
    for r in rows:
        base = UserOut.model_validate(r)
        out.append(base.model_copy(update={"credit_union_name": cu.name}))
    return {"items": out}


@router.post("/credit-unions/mine/members/{member_user_id}/remind-onboarding")
def remind_credit_union_member_onboarding(
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """CU staff: resend portal / approval links by email and SMS (same delivery as approval creation, no GHL)."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == int(cu_id)).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")

    member = db.query(User).filter(User.id == int(member_user_id)).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    member_role = member.role.value if hasattr(member.role, "value") else str(member.role)
    if member_role != "customer":
        raise HTTPException(status_code=400, detail="Target user is not a member account.")
    if int(member.credit_union_id or 0) != int(cu_id):
        raise HTTPException(status_code=403, detail="This member is not assigned to your credit union.")

    approval = (
        db.query(CuMemberApproval)
        .filter(
            CuMemberApproval.credit_union_id == int(cu_id),
            CuMemberApproval.user_id == int(member_user_id),
        )
        .order_by(CuMemberApproval.created_at.desc())
        .first()
    )

    base = _portal_base_url()
    signup_base = _platform_member_site_base_url()
    email_sent = False
    sms_sent = False
    to_email = (member.email or "").strip()
    phone = ((approval.member_phone if approval else None) or member.phone or "").strip()

    if approval:
        claim_url = f"{base}/approvals/{approval.approval_code}" if base else f"/approvals/{approval.approval_code}"
        tok = (cu.signup_token or "").strip()
        if tok and signup_base:
            join_url = f"{signup_base}/creditunions/join?token={tok}&approval={approval.approval_code}"
        elif tok:
            join_url = f"/creditunions/join?token={tok}&approval={approval.approval_code}"
        else:
            join_url = f"{base}/login" if base else "/login"

        if to_email:
            subject = f"{cu.name}: Reminder — your member portal & pre-approval"
            greet = (member.name or "").strip()
            salutation = f"Hello {greet},\n\n" if greet else "Hello,\n\n"
            body = (
                salutation
                + f"This is a reminder from {cu.name} regarding your auto loan pre-approval.\n\n"
                f"Approval amount: ${float(approval.loan_amount):,.2f}\n"
                f"Term: {approval.term_months} months\n"
                f"Rate: {float(approval.interest_rate or 0):.2f}% APR\n"
                f"Reference code: {approval.approval_code}\n\n"
                f"Open your approval letter:\n{claim_url}\n\n"
                f"Member portal (create account or sign in):\n{join_url}\n\n"
                f"If you have questions, contact your credit union.\n"
            )
            try:
                fe, rt = _cu_member_mail_from_reply(cu)
                send_email(to_email=to_email, subject=subject, body=body, from_email=fe, reply_to=rt)
                email_sent = True
            except EmailDeliveryError:
                email_sent = False

        if phone:
            sms_body = f"{cu.name}: Pre-approval reminder. View letter: {claim_url} Portal: {join_url}"
            sms_sent = send_sms(phone, sms_body[:480])
    else:
        login_url = f"{base}/login" if base else "/login"
        if to_email:
            subject = f"{cu.name}: Reminder — sign in to your member portal"
            greet = (member.name or "").strip()
            salutation = f"Hello {greet},\n\n" if greet else "Hello,\n\n"
            body = (
                salutation
                + f"Please sign in to your {cu.name} member portal using the link below.\n\n"
                f"{login_url}\n\n"
                f"If you need help, contact your credit union.\n"
            )
            try:
                fe, rt = _cu_member_mail_from_reply(cu)
                send_email(to_email=to_email, subject=subject, body=body, from_email=fe, reply_to=rt)
                email_sent = True
            except EmailDeliveryError:
                email_sent = False
        if phone:
            sms_body = f"{cu.name}: Member portal reminder. Sign in: {login_url}"
            sms_sent = send_sms(phone, sms_body[:480])

    if not email_sent and not sms_sent:
        raise HTTPException(
            status_code=400,
            detail="Could not send reminder: member has no email on file and no phone number.",
        )

    return {
        "ok": True,
        "member_user_id": int(member_user_id),
        "email_sent": email_sent,
        "sms_sent": sms_sent,
        "had_approval": approval is not None,
    }


@router.get("/credit-unions/mine/members/activity-summary")
def list_my_credit_union_member_activity_summary(
    limit: int = Query(2000, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Credit union staff: compact per-member activity counters for their assigned CU members."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")

    member_ids = [
        int(r[0])
        for r in db.query(User.id)
        .filter(
            User.credit_union_id == int(cu_id),
            User.role == UserRole.customer,
        )
        .order_by(User.id.desc())
        .limit(limit)
        .all()
    ]
    if not member_ids:
        return {"items": []}

    def _counts(model, user_col: str) -> dict[int, int]:
        col = getattr(model, user_col)
        rows = (
            db.query(col, func.count(model.id))
            .filter(col.in_(member_ids))
            .group_by(col)
            .all()
        )
        return {int(uid): int(cnt) for uid, cnt in rows if uid is not None}

    approvals = _counts(CuMemberApproval, "user_id")
    favorites = _counts(Favorite, "user_id")
    messages = _counts(BrokerMessage, "user_id")
    deals = _counts(Deal, "user_id")
    docs = _counts(DocumentSubmission, "user_id")

    out = []
    for uid in member_ids:
        out.append(
            {
                "user_id": uid,
                "approvals": approvals.get(uid, 0),
                "favorites": favorites.get(uid, 0),
                "messages": messages.get(uid, 0),
                "deals": deals.get(uid, 0),
                "docs": docs.get(uid, 0),
            }
        )
    return {"items": out}


def _serialize_member_invite(inv: CreditUnionMemberInvite, base: str) -> dict:
    rel_join = f"/creditunions/join?invite={inv.token}"
    rel_register = f"/register?invite={inv.token}"
    join_link = f"{base}{rel_join}" if base else rel_join
    register_link = f"{base}{rel_register}" if base else rel_register
    return {
        "id": inv.id,
        "invited_email": inv.invited_email,
        "invited_name": inv.invited_name,
        "invited_phone": inv.invited_phone,
        "token": inv.token,
        "used_at": str(inv.used_at) if inv.used_at else None,
        "created_at": str(inv.created_at) if inv.created_at else None,
        "join_link": join_link,
        "register_link": register_link,
        "is_used": inv.used_at is not None,
    }


@router.post("/credit-unions/mine/member-invites")
def create_credit_union_member_invite(
    payload: MemberInviteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Credit union staff: create a one-time signup link for a specific member."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")
    cu = db.query(CreditUnion).filter(CreditUnion.id == int(cu_id), CreditUnion.is_active == True).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")

    tok = secrets.token_urlsafe(24)[:64]
    while db.query(CreditUnionMemberInvite).filter(CreditUnionMemberInvite.token == tok).first():
        tok = secrets.token_urlsafe(24)[:64]

    inv = CreditUnionMemberInvite(
        credit_union_id=cu.id,
        token=tok,
        invited_email=payload.invited_email,
        invited_name=payload.invited_name,
        invited_phone=payload.invited_phone,
        created_by_user_id=user.id,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    base = _portal_base_url()
    return {"item": _serialize_member_invite(inv, base)}


@router.get("/credit-unions/mine/member-invites")
def list_credit_union_member_invites(
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "credit_union":
        raise HTTPException(status_code=403, detail="Credit union staff only.")
    cu_id = getattr(user, "credit_union_id", None)
    if not cu_id:
        raise HTTPException(status_code=403, detail="No credit union assigned to this account.")
    rows = (
        db.query(CreditUnionMemberInvite)
        .filter(CreditUnionMemberInvite.credit_union_id == int(cu_id))
        .order_by(CreditUnionMemberInvite.created_at.desc())
        .limit(limit)
        .all()
    )
    base = _portal_base_url()
    return {"items": [_serialize_member_invite(r, base) for r in rows]}


# ---------- Pre-approvals ----------
class ApprovalCreate(BaseModel):
    loan_amount: float
    term_months: int
    interest_rate: float
    special_notes: Optional[str] = None
    approval_code: Optional[str] = None
    member_name: Optional[str] = None
    member_phone: Optional[str] = None
    member_email: Optional[str] = None


class ApprovalUpdate(BaseModel):
    status: Optional[str] = None
    approval_code: Optional[str] = None
    interest_rate: Optional[float] = None
    loan_amount: Optional[float] = None
    term_months: Optional[int] = None
    special_notes: Optional[str] = None
    member_name: Optional[str] = None
    member_phone: Optional[str] = None
    member_email: Optional[str] = None


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


def _can_create_cu_preapproval(user: User, cu_id: int) -> bool:
    """Pre-approvals are issued by credit union staff only, not platform admins."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role == "credit_union" and getattr(user, "credit_union_id", None) == cu_id


def _validate_approval_reference_code(code: str) -> str:
    c = (code or "").strip()
    if not c or len(c) > 64:
        raise HTTPException(status_code=400, detail="Reference code must be 1–64 characters.")
    if not _APPROVAL_CODE_RE.match(c):
        raise HTTPException(
            status_code=400,
            detail="Reference code may only contain letters, numbers, hyphens, and underscores.",
        )
    return c


def _cu_member_mail_from_reply(cu: CreditUnion) -> tuple[Optional[str], Optional[str]]:
    """(from_email, reply_to) for CU pre-approval and member reminder mail.

    ``CU_APPROVAL_FROM_EMAIL`` wins (e.g. noreply@…); replies go to ``contact_email`` when set.
    Otherwise, if ``CU_APPROVAL_FROM_CU_CONTACT`` is true, use the CU's ``contact_email`` as From.
    """
    override = (settings.cu_approval_from_email or "").strip()
    if override:
        reply = (cu.contact_email or "").strip() or None
        return override, reply
    if settings.cu_approval_from_cu_contact:
        contact = (cu.contact_email or "").strip()
        if contact:
            return contact, None
    return None, None


def _serialize_approval(a: CuMemberApproval, include_cu_name: bool = False) -> dict:
    out = {
        "id": a.id,
        "credit_union_id": a.credit_union_id,
        "user_id": a.user_id,
        "loan_amount": float(a.loan_amount) if a.loan_amount is not None else None,
        "term_months": a.term_months,
        "interest_rate": float(a.interest_rate) if a.interest_rate is not None else None,
        "special_notes": a.special_notes,
        "approval_code": a.approval_code,
        "member_name": a.member_name,
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
    if not _can_create_cu_preapproval(user, cu_id):
        raise HTTPException(
            status_code=403,
            detail="Only credit union staff can create pre-approvals for their organization.",
        )
    if payload.interest_rate < 0:
        raise HTTPException(status_code=400, detail="Rate must be a positive number.")
    desired = (payload.approval_code or "").strip()
    if desired:
        code = _validate_approval_reference_code(desired)
        if db.query(CuMemberApproval).filter(CuMemberApproval.approval_code == code).first():
            raise HTTPException(
                status_code=400,
                detail="This reference code is already in use. Choose a different one.",
            )
    else:
        code = None
        for _ in range(24):
            candidate = secrets.token_urlsafe(12).upper()[:16]
            if not db.query(CuMemberApproval).filter(CuMemberApproval.approval_code == candidate).first():
                code = candidate
                break
        if not code:
            raise HTTPException(status_code=500, detail="Could not assign a unique approval code.")
    approval = CuMemberApproval(
        credit_union_id=cu_id,
        loan_amount=Decimal(str(payload.loan_amount)),
        term_months=payload.term_months,
        interest_rate=Decimal(str(payload.interest_rate)),
        special_notes=(payload.special_notes or "").strip() or None,
        approval_code=code,
        member_name=(payload.member_name or "").strip() or None,
        member_phone=(payload.member_phone or "").strip() or None,
        member_email=(payload.member_email or "").strip() or None,
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    portal_base = _portal_base_url()
    platform_base = _platform_member_site_base_url()
    claim_url = (
        f"{portal_base}/approvals/{approval.approval_code}"
        if portal_base
        else f"/approvals/{approval.approval_code}"
    )
    join_url = (
        f"{platform_base}/creditunions/join?token={cu.signup_token}&approval={approval.approval_code}"
        if platform_base
        else f"/creditunions/join?token={cu.signup_token}&approval={approval.approval_code}"
    )
    sms_sent = False
    email_sent = False
    if approval.member_phone:
        body = f"{cu.name}: You have a pre-approved auto loan. Create an account or log in to view: {claim_url}"
        sms_sent = send_sms(approval.member_phone, body)
    if approval.member_email:
        subject = f"{cu.name}: Your auto loan pre-approval is ready"
        greet = (approval.member_name or "").strip()
        salutation = f"Hello {greet},\n\n" if greet else "Hello,\n\n"
        body = (
            salutation
            + f"You have been pre-approved for an auto loan with {cu.name}.\n\n"
            f"Approval amount: ${float(approval.loan_amount):,.2f}\n"
            f"Term: {approval.term_months} months\n"
            f"Rate: {float(approval.interest_rate):.2f}% APR\n"
            f"Reference code: {approval.approval_code}\n\n"
            f"Open your approval letter:\n{claim_url}\n\n"
            f"Create/sign in to your member portal:\n{join_url}\n\n"
            f"If you have questions, reply to this email or contact your credit union.\n"
        )
        try:
            fe, rt = _cu_member_mail_from_reply(cu)
            send_email(
                to_email=approval.member_email,
                subject=subject,
                body=body,
                from_email=fe,
                reply_to=rt,
            )
            email_sent = True
        except EmailDeliveryError:
            email_sent = False
    return {
        "item": _serialize_approval(approval),
        "approval_code": approval.approval_code,
        "claim_url": claim_url,
        "join_url": join_url,
        "sms_sent": sms_sent,
        "email_sent": email_sent,
    }


@router.get("/approvals/mine")
def list_my_approvals(
    member_user_id: Optional[int] = Query(None),
    credit_union_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    query = db.query(CuMemberApproval)
    if role in ("super_admin", "credit_union"):
        if member_user_id is not None:
            scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
            query = query.filter(CuMemberApproval.user_id == scoped_user_id)
        elif role == "super_admin" and credit_union_id is not None:
            query = query.filter(CuMemberApproval.credit_union_id == int(credit_union_id))
        elif role == "credit_union" and user.credit_union_id:
            query = query.filter(CuMemberApproval.credit_union_id == user.credit_union_id)
        rows = query.order_by(CuMemberApproval.created_at.desc()).limit(100).all()
    else:
        if member_user_id is not None:
            scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
            query = query.filter(CuMemberApproval.user_id == scoped_user_id)
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
    base = _portal_base_url()
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
    if (
        payload.status is None
        and payload.approval_code is None
        and payload.interest_rate is None
        and payload.loan_amount is None
        and payload.term_months is None
        and payload.special_notes is None
        and payload.member_name is None
        and payload.member_phone is None
        and payload.member_email is None
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide one or more fields to update "
                "(status, approval_code, interest_rate, loan_amount, term_months, "
                "special_notes, member_name, member_phone, member_email)."
            ),
        )

    if payload.approval_code is not None:
        if not _can_create_cu_preapproval(user, cu_id):
            raise HTTPException(
                status_code=403,
                detail="Only credit union staff can change the reference code.",
            )
        new_code = _validate_approval_reference_code(payload.approval_code)
        taken = (
            db.query(CuMemberApproval)
            .filter(
                CuMemberApproval.approval_code == new_code,
                CuMemberApproval.id != approval.id,
            )
            .first()
        )
        if taken:
            raise HTTPException(
                status_code=400,
                detail="This reference code is already in use. Choose a different one.",
            )
        approval.approval_code = new_code

    if payload.status is not None:
        if not _can_manage_cu(user, cu_id):
            raise HTTPException(status_code=403, detail="Not allowed to update approvals for this credit union.")
        status = (payload.status or "").strip().lower()
        if status not in _ALLOWED_APPROVAL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {', '.join(sorted(_ALLOWED_APPROVAL_STATUSES))}.",
            )
        approval.status = status

    if payload.interest_rate is not None:
        if payload.interest_rate < 0:
            raise HTTPException(status_code=400, detail="Rate must be a positive number.")
        approval.interest_rate = Decimal(str(payload.interest_rate))
    if payload.loan_amount is not None:
        if payload.loan_amount <= 0:
            raise HTTPException(status_code=400, detail="Loan amount must be greater than zero.")
        approval.loan_amount = Decimal(str(payload.loan_amount))
    if payload.term_months is not None:
        if payload.term_months <= 0:
            raise HTTPException(status_code=400, detail="Term must be at least 1 month.")
        approval.term_months = int(payload.term_months)
    if payload.special_notes is not None:
        approval.special_notes = (payload.special_notes or "").strip() or None
    if payload.member_name is not None:
        approval.member_name = (payload.member_name or "").strip() or None
    if payload.member_phone is not None:
        approval.member_phone = (payload.member_phone or "").strip() or None
    if payload.member_email is not None:
        approval.member_email = (payload.member_email or "").strip().lower() or None
    db.commit()
    db.refresh(approval)
    return {"item": _serialize_approval(approval)}


@router.delete("/admin/credit-unions/{cu_id}/approvals/{approval_id}")
def delete_approval(
    cu_id: int,
    approval_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_create_cu_preapproval(user, cu_id):
        raise HTTPException(
            status_code=403,
            detail="Only credit union staff can delete pre-approvals for their organization.",
        )
    approval = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.id == approval_id, CuMemberApproval.credit_union_id == cu_id)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    db.delete(approval)
    db.commit()
    return {"deleted": True, "id": approval_id}


@router.post("/admin/credit-unions/{cu_id}/approvals/{approval_id}/resend-invite")
def resend_approval_invite(
    cu_id: int,
    approval_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_create_cu_preapproval(user, cu_id):
        raise HTTPException(
            status_code=403,
            detail="Only credit union staff can resend pre-approval invites.",
        )
    cu = db.query(CreditUnion).filter(CreditUnion.id == cu_id).first()
    if not cu:
        raise HTTPException(status_code=404, detail="Credit union not found.")
    approval = (
        db.query(CuMemberApproval)
        .filter(CuMemberApproval.id == approval_id, CuMemberApproval.credit_union_id == cu_id)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.user_id is not None:
        raise HTTPException(status_code=400, detail="Approval already claimed by a member.")

    portal_base = _portal_base_url()
    platform_base = _platform_member_site_base_url()
    claim_url = (
        f"{portal_base}/approvals/{approval.approval_code}"
        if portal_base
        else f"/approvals/{approval.approval_code}"
    )
    join_url = (
        f"{platform_base}/creditunions/join?token={cu.signup_token}&approval={approval.approval_code}"
        if platform_base
        else f"/creditunions/join?token={cu.signup_token}&approval={approval.approval_code}"
    )
    sms_sent = False
    email_sent = False
    if approval.member_phone:
        body = f"{cu.name}: Reminder — your pre-approved auto loan is ready. View letter: {claim_url}"
        sms_sent = send_sms(approval.member_phone, body[:480])
    if approval.member_email:
        subject = f"{cu.name}: Reminder — your auto loan pre-approval is ready"
        greet = (approval.member_name or "").strip()
        salutation = f"Hello {greet},\n\n" if greet else "Hello,\n\n"
        body = (
            salutation
            + f"This is a reminder from {cu.name} regarding your auto loan pre-approval.\n\n"
            f"Approval amount: ${float(approval.loan_amount):,.2f}\n"
            f"Term: {approval.term_months} months\n"
            f"Rate: {float(approval.interest_rate or 0):.2f}% APR\n"
            f"Reference code: {approval.approval_code}\n\n"
            f"Open your approval letter:\n{claim_url}\n\n"
            f"Create/sign in to your member portal:\n{join_url}\n\n"
            f"If you have questions, reply to this email or contact your credit union.\n"
        )
        try:
            fe, rt = _cu_member_mail_from_reply(cu)
            send_email(
                to_email=approval.member_email,
                subject=subject,
                body=body,
                from_email=fe,
                reply_to=rt,
            )
            email_sent = True
        except EmailDeliveryError:
            email_sent = False
    if not email_sent and not sms_sent:
        raise HTTPException(
            status_code=400,
            detail="Could not resend invite: approval has no member email and no member phone.",
        )
    return {
        "ok": True,
        "approval_id": approval_id,
        "email_sent": email_sent,
        "sms_sent": sms_sent,
        "claim_url": claim_url,
        "join_url": join_url,
    }


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
    if user.credit_union_id is None:
        user.credit_union_id = approval.credit_union_id
    db.commit()
    db.refresh(approval)
    return {"item": _serialize_approval(approval), "claimed": True}
