from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.lender_rate import LenderRate
from app.models.offer_override import OfferOverride
from app.schemas.payments import PaymentEstimateResponse
from app.services.lender_logic import infer_credit_tier, select_best_rate
from app.services.payments import estimate_monthly_payment, resolve_price
from app.services.legacy_tables import load_legacy_tables
from app.core.database import engine

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/estimate", response_model=PaymentEstimateResponse)
def estimate_payment(
    vin: str,
    apr: float = Query(5.0),
    term: int = Query(72),
    credit_score: Optional[int] = Query(None),
    down: float = Query(0.0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
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
    if not row:
        raise HTTPException(status_code=404, detail="VIN not found")

    mapping = row._mapping
    vehicle_type = str(mapping.get("vehicle_type") or "new").lower()
    offer = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
    discounted = float(offer.discounted_price) if offer and offer.discounted_price is not None else None
    override_monthly = float(offer.monthly_payment) if offer and offer.monthly_payment is not None else None

    msrp = float(mapping.get("msrp")) if mapping.get("msrp") is not None else None
    listed_price = float(mapping.get("listed_price")) if mapping.get("listed_price") is not None else None

    price = resolve_price(vehicle_type, msrp, discounted, listed_price)
    if price is None:
        raise HTTPException(status_code=400, detail="Vehicle price unavailable")

    effective_apr = apr
    effective_term = term
    inferred_tier = infer_credit_tier(credit_score)
    rates = db.query(LenderRate).all()
    best_rate = select_best_rate(rates, tier=inferred_tier, vehicle_type=vehicle_type)
    if best_rate is not None:
        effective_apr = float(best_rate.apr)
        effective_term = min(int(effective_term), int(best_rate.max_term_months))

    monthly = (
        override_monthly
        if vehicle_type == "new" and override_monthly is not None
        else estimate_monthly_payment(price, effective_apr, effective_term, down)
    )
    return PaymentEstimateResponse(
        vin=vin,
        vehicle_type=vehicle_type,
        apr=effective_apr,
        term=effective_term,
        down=down,
        vehicle_price=price,
        estimated_monthly=round(monthly, 2),
        primary_offer_monthly=round(override_monthly, 2) if vehicle_type == "new" and override_monthly is not None else None,
        credit_tier=inferred_tier,
    )
