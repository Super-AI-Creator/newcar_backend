from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_role
from app.models.lender_rate import LenderRate
from app.schemas.lenders import LenderRateIn

router = APIRouter(prefix="/lenders", tags=["lenders"])


def _serialize(row: LenderRate) -> dict:
    return {
        "id": int(row.id),
        "lender_name": row.lender_name,
        "credit_tier": row.credit_tier,
        "vehicle_type": row.vehicle_type,
        "apr": float(row.apr),
        "max_term_months": int(row.max_term_months),
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@router.get("/rates")
def list_rates(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    _ = user
    rows = (
        db.query(LenderRate)
        .order_by(LenderRate.credit_tier.asc(), LenderRate.apr.asc(), LenderRate.max_term_months.desc())
        .all()
    )
    return {"items": [_serialize(row) for row in rows]}


@router.post("/rates")
def create_rate(payload: LenderRateIn, db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    _ = user
    row = LenderRate(
        lender_name=payload.lender_name.strip(),
        credit_tier=payload.credit_tier.strip().upper(),
        vehicle_type=payload.vehicle_type.strip().lower(),
        apr=payload.apr,
        max_term_months=payload.max_term_months,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.put("/rates/{rate_id}")
def update_rate(
    rate_id: int,
    payload: LenderRateIn,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    _ = user
    row = db.query(LenderRate).filter(LenderRate.id == rate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    row.lender_name = payload.lender_name.strip()
    row.credit_tier = payload.credit_tier.strip().upper()
    row.vehicle_type = payload.vehicle_type.strip().lower()
    row.apr = payload.apr
    row.max_term_months = payload.max_term_months
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/rates/{rate_id}")
def delete_rate(rate_id: int, db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    _ = user
    row = db.query(LenderRate).filter(LenderRate.id == rate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}
