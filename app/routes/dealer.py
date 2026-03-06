from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_db, require_role
from app.models.enums import OfferSource
from app.models.offer_override import OfferOverride
from app.services.legacy_tables import build_inventory_query, load_legacy_tables
from app.services.offers import set_offer_visibility

router = APIRouter(prefix="/dealer", tags=["dealer"])


class DealerOfferUpdate(BaseModel):
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    discounted_price: Optional[float] = None
    term_months: Optional[int] = None
    miles_per_year: Optional[int] = None


class DealerOfferYmmUpdate(DealerOfferUpdate):
    year: int
    make: str
    model: str
    vehicle_type: Optional[str] = None


def _payload_dict(payload: DealerOfferUpdate) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


def _set_offer_fields(offer: OfferOverride, payload_data: dict):
    for field in ["down_payment", "monthly_payment", "discounted_price", "term_months", "miles_per_year"]:
        if field in payload_data:
            offer.__setattr__(field, payload_data.get(field))


@router.put("/offers/{vin}")
def update_offer(
    vin: str,
    payload: DealerOfferUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("dealer")),
):
    normalized_vin = (vin or "").strip().upper()
    if not normalized_vin:
        raise HTTPException(status_code=400, detail="VIN is required.")

    tables = load_legacy_tables(engine)
    listings = tables["vehicle_listings"]

    # Dealer can set offers for any vehicle in the list (no source restriction).
    exists = (
        db.execute(select(listings.c.vin).where(listings.c.vin == normalized_vin).limit(1)).fetchone()
        is not None
    )
    if not exists:
        raise HTTPException(status_code=404, detail="VIN not found in vehicle list")

    offer = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not offer:
        offer = OfferOverride(vin=normalized_vin, source=OfferSource.dealer, updated_by_user_id=user.id)
        db.add(offer)

    _set_offer_fields(offer, _payload_dict(payload))
    offer.source = OfferSource.dealer
    offer.updated_by_user_id = user.id
    set_offer_visibility(offer)
    db.commit()

    return {"status": "updated", "updated": True}


@router.put("/offers-by-ymm")
def update_offer_by_ymm(
    payload: DealerOfferYmmUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("dealer")),
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

    existing = db.query(OfferOverride).filter(OfferOverride.vin.in_(vins)).all()
    existing_by_vin = {str(row.vin).upper(): row for row in existing}
    payload_data = _payload_dict(payload)

    for vin in vins:
        row = existing_by_vin.get(vin)
        if not row:
            row = OfferOverride(vin=vin, source=OfferSource.dealer, updated_by_user_id=user.id)
            db.add(row)
        _set_offer_fields(row, payload_data)
        row.source = OfferSource.dealer
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
