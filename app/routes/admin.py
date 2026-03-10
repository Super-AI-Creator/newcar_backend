from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_db, require_role
from app.models.enums import OfferSource
from app.models.lead_request import LeadRequest
from app.models.offer_override import OfferOverride
from app.models.model_score import ModelScore
from app.models.sheet_sources_meta import SheetSourceMeta
from app.services.offers import set_offer_visibility
from app.services.lead_delivery import build_lead_webhook_payload, is_lead_webhook_enabled, send_lead_webhook
from app.services.legacy_tables import build_inventory_query, load_legacy_tables
from app.services.sheets_runner import run_sheets_sync

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sources")
def sources(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    tables = load_legacy_tables(engine)
    dealer_sources = tables["dealer_sources"]
    query = select(dealer_sources)

    rows = db.execute(query).fetchall()
    results = []
    for row in rows:
        mapping = row._mapping
        results.append({k: v for k, v in mapping.items()})

    return {"items": results}


@router.post("/sync-sheets")
def sync_sheets(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    return _sync_sheets(db)


@router.post("/sync")
def sync_sheets_alias(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    return _sync_sheets(db)


@router.get("/sync-status")
def sync_status(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    rows = (
        db.query(SheetSourceMeta)
        .filter(SheetSourceMeta.sheet_name.in_(["offers", "scores"]))
        .order_by(SheetSourceMeta.last_synced_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "sheet_name": row.sheet_name,
                "sheet_id": row.sheet_id,
                "tab_name": row.tab_name,
                "last_synced_at": str(row.last_synced_at) if row.last_synced_at else None,
                "last_row_hash": row.last_row_hash,
                "last_error": row.last_error,
            }
            for row in rows
        ],
        "counts": {
            "offer_overrides": db.query(func.count(OfferOverride.id)).scalar() or 0,
            "model_scores": db.query(func.count(ModelScore.id)).scalar() or 0,
        },
    }


@router.get("/lead-delivery")
def lead_delivery_logs(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    query = db.query(LeadRequest)
    if status in {"pending", "sent", "failed", "skipped"}:
        query = query.filter(LeadRequest.webhook_status == status)
    if q:
        needle = q.strip()
        if needle:
            query = query.filter(
                (LeadRequest.email.ilike(f"%{needle}%"))
                | (LeadRequest.phone.ilike(f"%{needle}%"))
                | (LeadRequest.vin.ilike(f"%{needle}%"))
                | (LeadRequest.name.ilike(f"%{needle}%"))
            )

    rows = query.order_by(LeadRequest.created_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "lead_id": int(row.id),
                "created_at": str(row.created_at) if row.created_at else None,
                "name": row.name,
                "email": row.email,
                "phone": row.phone,
                "vin": row.vin,
                "source": row.source,
                "webhook_status": row.webhook_status,
                "webhook_attempts": int(row.webhook_attempts or 0),
                "webhook_last_error": row.webhook_last_error,
                "webhook_last_attempt_at": str(row.webhook_last_attempt_at) if row.webhook_last_attempt_at else None,
                "webhook_delivered_at": str(row.webhook_delivered_at) if row.webhook_delivered_at else None,
            }
            for row in rows
        ]
    }


@router.post("/lead-delivery/{lead_id}/retry")
def retry_lead_delivery(
    lead_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    if not is_lead_webhook_enabled():
        raise HTTPException(status_code=400, detail="Lead webhook is not configured.")

    row = db.query(LeadRequest).filter(LeadRequest.id == lead_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    row.webhook_status = "pending"
    row.webhook_last_error = None
    db.commit()
    db.refresh(row)

    background_tasks.add_task(send_lead_webhook, build_lead_webhook_payload(row))
    return {"queued": True, "lead_id": int(row.id), "webhook_status": row.webhook_status}


def _sync_sheets(db: Session):
    if not (db and engine):
        raise HTTPException(status_code=500, detail="Database not ready")
    return run_sheets_sync(db)


class OfferOverrideUpdate(BaseModel):
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    discounted_price: Optional[float] = None
    term_months: Optional[int] = None
    miles_per_year: Optional[int] = None


class OfferOverrideYmmUpdate(OfferOverrideUpdate):
    year: int
    make: str
    model: str
    vehicle_type: Optional[str] = None


def _normalize_vin(vin: str) -> str:
    normalized = (vin or "").strip().upper()
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="VIN must be at least 8 characters.")
    return normalized


@router.get("/offer-overrides")
def list_offer_overrides(
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    query = db.query(OfferOverride)
    if source in {"sheet", "dealer", "broker"}:
        query = query.filter(OfferOverride.source == source)
    if q:
        query = query.filter(OfferOverride.vin.ilike(f"%{q.strip()}%"))
    rows = query.order_by(OfferOverride.updated_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "vin": row.vin,
                "source": row.source.value if hasattr(row.source, "value") else row.source,
                "down_payment": float(row.down_payment) if row.down_payment is not None else None,
                "monthly_payment": float(row.monthly_payment) if row.monthly_payment is not None else None,
                "discounted_price": float(row.discounted_price) if row.discounted_price is not None else None,
                "term_months": int(row.term_months) if row.term_months is not None else None,
                "miles_per_year": int(row.miles_per_year) if row.miles_per_year is not None else None,
                "updated_at": str(row.updated_at) if row.updated_at else None,
            }
            for row in rows
        ]
    }


@router.put("/offer-overrides/{vin}")
def upsert_offer_override(
    vin: str,
    payload: OfferOverrideUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    normalized_vin = _normalize_vin(vin)
    row = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not row:
        row = OfferOverride(vin=normalized_vin, source=OfferSource.broker, updated_by_user_id=user.id)
        db.add(row)

    row.down_payment = payload.down_payment
    row.monthly_payment = payload.monthly_payment
    row.discounted_price = payload.discounted_price
    row.term_months = payload.term_months
    row.miles_per_year = payload.miles_per_year
    row.source = OfferSource.broker
    row.updated_by_user_id = user.id
    set_offer_visibility(row)
    db.commit()
    db.refresh(row)

    return {
        "status": "updated",
        "vin": row.vin,
        "source": row.source.value if hasattr(row.source, "value") else row.source,
        "down_payment": float(row.down_payment) if row.down_payment is not None else None,
        "monthly_payment": float(row.monthly_payment) if row.monthly_payment is not None else None,
        "discounted_price": float(row.discounted_price) if row.discounted_price is not None else None,
        "term_months": int(row.term_months) if row.term_months is not None else None,
        "miles_per_year": int(row.miles_per_year) if row.miles_per_year is not None else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@router.delete("/offer-overrides/{vin}")
def delete_offer_override(
    vin: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    normalized_vin = _normalize_vin(vin)
    row = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer override not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "vin": normalized_vin}


@router.put("/offer-overrides-by-ymm")
def upsert_offer_override_by_ymm(
    payload: OfferOverrideYmmUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    filters = {
        "year": payload.year,
        "make": payload.make,
        "model": payload.model,
    }
    if payload.vehicle_type in {"new", "used", "all"}:
        filters["vehicle_type"] = payload.vehicle_type

    rows = db.execute(build_inventory_query(engine, filters)).fetchall()
    vins = sorted(
        {
            str(row._mapping.get("vin")).strip().upper()
            for row in rows
            if row._mapping.get("vin")
        }
    )
    if not vins:
        raise HTTPException(status_code=404, detail="No vehicles found for year/make/model.")

    for vin in vins:
        row = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
        if not row:
            row = OfferOverride(vin=vin, source=OfferSource.broker, updated_by_user_id=user.id)
            db.add(row)
        row.down_payment = payload.down_payment
        row.monthly_payment = payload.monthly_payment
        row.discounted_price = payload.discounted_price
        row.term_months = payload.term_months
        row.miles_per_year = payload.miles_per_year
        row.source = OfferSource.broker
        row.updated_by_user_id = user.id
        set_offer_visibility(row)

    db.commit()
    return {
        "status": "updated",
        "updated_count": len(vins),
        "year": payload.year,
        "make": payload.make,
        "model": payload.model,
        "vins": vins[:200],
    }
