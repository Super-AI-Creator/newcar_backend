from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, case, func
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_current_user, get_db, require_role
from app.models.credit_application import CreditApplication
from app.models.lender_rate import LenderRate
from app.models.offer_override import OfferOverride
from app.models.user import User
from app.schemas.misc import CreditApplicationIn, PublicCreditApplicationIn
from app.services.credit_application_delivery import notify_credit_application_submitted
from app.services.credit_application_format import enrich_payload_with_formatted
from app.services.lender_logic import infer_credit_tier, select_best_rate
from app.services.legacy_tables import load_legacy_tables
from app.services.payments import estimate_monthly_payment, resolve_price
from app.services.cu_member_scope import resolve_member_scope_user_id

router = APIRouter(prefix="/credit", tags=["credit"])


def _viewer_is_super_admin(viewer: Optional[User]) -> bool:
    if viewer is None:
        return False
    role_value = viewer.role.value if hasattr(viewer.role, "value") else str(viewer.role)
    return role_value == "super_admin"


def _serialize_credit_application(
    row: CreditApplication,
    customer: Optional[User] = None,
    reviewer: Optional[User] = None,
    viewer: Optional[User] = None,
) -> dict:
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    if _viewer_is_super_admin(viewer) and payload:
        base = {k: v for k, v in payload.items() if k not in ("formatted_plain", "formatted_html")}
        payload = enrich_payload_with_formatted(dict(base), mask_sensitive=False)
    customer_name = (
        customer.name
        if customer
        else " ".join([(payload.get("first_name") or "").strip(), (payload.get("last_name") or "").strip()]).strip() or None
    )
    customer_email = customer.email if customer else payload.get("email")

    return {
        "id": int(row.id),
        "user_id": int(row.user_id) if row.user_id is not None else None,
        "vin": row.vin,
        "source": row.source,
        "status": row.status,
        "broker_note": row.broker_note,
        "reviewed_by_user_id": int(row.reviewed_by_user_id) if row.reviewed_by_user_id is not None else None,
        "reviewed_by_name": reviewer.name if reviewer else None,
        "reviewed_by_email": reviewer.email if reviewer else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "payload_json": payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer.phone if customer else payload.get("home_phone"),
    }


@router.post("/apply")
def apply_credit(
    payload: CreditApplicationIn,
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    raw = payload.payload_json if isinstance(payload.payload_json, dict) else {}
    merged = enrich_payload_with_formatted(raw, mask_sensitive=False)
    app_row = CreditApplication(
        user_id=scoped_user_id,
        vin=payload.vin,
        payload_json=merged,
        source="authenticated",
        status="submitted",
    )
    db.add(app_row)
    db.commit()
    db.refresh(app_row)
    notify_credit_application_submitted(
        application_id=int(app_row.id),
        source="authenticated",
        vin=app_row.vin,
        payload_json=app_row.payload_json if isinstance(app_row.payload_json, dict) else merged,
        created_at=app_row.created_at,
    )
    return {"status": "received"}


@router.post("/public-apply")
def apply_credit_public(payload: PublicCreditApplicationIn, db: Session = Depends(get_db)):
    if not payload.agreed_to_terms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You must agree to terms before submitting.")

    base = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    merged = enrich_payload_with_formatted(base, mask_sensitive=False)
    app_row = CreditApplication(
        user_id=None,
        vin=payload.vin,
        payload_json=merged,
        source="public",
        status="submitted",
    )
    db.add(app_row)
    db.commit()
    db.refresh(app_row)
    notify_credit_application_submitted(
        application_id=int(app_row.id),
        source="public",
        vin=app_row.vin,
        payload_json=app_row.payload_json if isinstance(app_row.payload_json, dict) else merged,
        created_at=app_row.created_at,
    )
    return {"status": "received"}


@router.get("/applications")
def list_credit_applications(
    status_filter: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "admin", "super_admin")),
):
    _ = user
    query = db.query(CreditApplication).order_by(CreditApplication.created_at.desc())
    if status_filter:
        query = query.filter(CreditApplication.status == status_filter.strip().lower())
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            (CreditApplication.vin.ilike(needle))
            | (CreditApplication.source.ilike(needle))
            | (func.cast(CreditApplication.id, String).ilike(needle))
        )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    user_ids = {int(row.user_id) for row in rows if row.user_id is not None}
    reviewer_ids = {int(row.reviewed_by_user_id) for row in rows if row.reviewed_by_user_id is not None}
    users = db.query(User).filter(User.id.in_(list(user_ids | reviewer_ids))).all() if (user_ids or reviewer_ids) else []
    user_map = {int(item.id): item for item in users}

    items = [
        _serialize_credit_application(
            row,
            customer=user_map.get(int(row.user_id)) if row.user_id is not None else None,
            reviewer=user_map.get(int(row.reviewed_by_user_id)) if row.reviewed_by_user_id is not None else None,
            viewer=user,
        )
        for row in rows
    ]
    return {"items": items, "total": total}


@router.patch("/applications/{application_id}")
def update_credit_application(
    application_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "admin", "super_admin")),
):
    row = db.query(CreditApplication).filter(CreditApplication.id == application_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Credit application not found")

    next_status = payload.get("status")
    if isinstance(next_status, str) and next_status.strip():
        row.status = next_status.strip().lower()
        row.reviewed_by_user_id = int(user.id)
        row.reviewed_at = datetime.utcnow()

    broker_note = payload.get("broker_note")
    if isinstance(broker_note, str):
        row.broker_note = broker_note.strip() or None

    db.commit()
    db.refresh(row)
    customer = db.query(User).filter(User.id == row.user_id).first() if row.user_id is not None else None
    reviewer = db.query(User).filter(User.id == row.reviewed_by_user_id).first() if row.reviewed_by_user_id is not None else None
    return _serialize_credit_application(row, customer=customer, reviewer=reviewer, viewer=user)


@router.get("/mine")
def list_my_credit_applications(
    vin: Optional[str] = Query(None),
    member_user_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    scoped_customer = user if int(scoped_user_id) == int(user.id) else db.query(User).filter(User.id == scoped_user_id).first()
    normalized_email = (scoped_customer.email if scoped_customer else user.email or "").strip().lower()
    query = db.query(CreditApplication).filter(
        (CreditApplication.user_id == scoped_user_id)
        | (
            (CreditApplication.user_id.is_(None))
            & (func.lower(func.trim(func.json_unquote(func.json_extract(CreditApplication.payload_json, "$.email")))) == normalized_email)
        )
    ).order_by(CreditApplication.created_at.desc())
    if vin and vin.strip():
        query = query.filter(CreditApplication.vin == vin.strip().upper())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [_serialize_credit_application(row, customer=scoped_customer) for row in rows]
    return {"items": items, "total": total}


@router.get("/prequal")
def prequal(
    credit_score: int,
    gross_monthly_income: float,
    vehicle_type: str = "new",
    down_payment: float = 0.0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ = user
    tier = infer_credit_tier(credit_score)
    rates = db.query(LenderRate).all()
    best = select_best_rate(rates, tier=tier, vehicle_type=vehicle_type)

    apr = float(best.apr) if best is not None else 5.0
    max_term = int(best.max_term_months) if best is not None else 72

    # Quick affordability heuristic for shopping-first UX: 15% gross-income ceiling.
    target_payment = max(0.0, gross_monthly_income * 0.15)
    principal = target_payment * max_term - down_payment
    estimated_budget = max(0.0, round(principal, 2))
    return {
        "tier": tier,
        "apr": round(apr, 3),
        "max_term_months": max_term,
        "target_payment": round(target_payment, 2),
        "estimated_budget": estimated_budget,
    }


@router.get("/lender-options")
def lender_options(
    credit_score: int = Query(...),
    vehicle_type: str = Query("new"),
    vin: Optional[str] = Query(None),
    down_payment: float = Query(0.0),
    term_months: int = Query(72),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _ = user
    tier = infer_credit_tier(credit_score)
    normalized_type = (vehicle_type or "new").strip().lower()
    rates = db.query(LenderRate).all()
    scoped = [
        row
        for row in rates
        if (row.credit_tier or "").strip().upper() == tier
        and ((row.vehicle_type or "all").strip().lower() in {"all", normalized_type})
    ]
    if not scoped:
        scoped = [row for row in rates if (row.credit_tier or "").strip().upper() == tier]

    price = None
    resolved_type = normalized_type
    if vin:
        tables = load_legacy_tables(engine)
        listings = tables["vehicle_listings"]
        status_col = listings.c.status if "status" in listings.c else None
        last_seen_col = listings.c.last_seen_at if "last_seen_at" in listings.c else None

        query = listings.select().where(listings.c.vin == vin)
        if status_col is not None:
            query = query.order_by(case((func.lower(status_col) == "active", 1), else_=0).desc())
        if last_seen_col is not None:
            query = query.order_by(last_seen_col.desc())
        row = db.execute(query.limit(1)).fetchone()
        if row:
            mapping = row._mapping
            resolved_type = str(mapping.get("vehicle_type") or normalized_type).lower()
            offer = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
            discounted = float(offer.discounted_price) if offer and offer.discounted_price is not None else None
            msrp = float(mapping.get("msrp")) if mapping.get("msrp") is not None else None
            listed_price = float(mapping.get("listed_price")) if mapping.get("listed_price") is not None else None
            price = resolve_price(resolved_type, msrp, discounted, listed_price)

    items = []
    for row in sorted(scoped, key=lambda r: (float(r.apr), -(r.max_term_months or 0))):
        apr = float(row.apr)
        max_term = int(row.max_term_months)
        effective_term = min(int(term_months), max_term)
        monthly = None
        if price is not None:
            monthly = round(estimate_monthly_payment(float(price), apr, effective_term, float(down_payment)), 2)
        items.append(
            {
                "lender_name": row.lender_name,
                "credit_tier": row.credit_tier,
                "vehicle_type": row.vehicle_type,
                "apr": apr,
                "max_term_months": max_term,
                "effective_term_months": effective_term,
                "estimated_monthly": monthly,
            }
        )

    return {
        "tier": tier,
        "vehicle_type": resolved_type,
        "vin": vin,
        "vehicle_price": round(float(price), 2) if price is not None else None,
        "items": items[:10],
    }
