from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.deps import get_db, security
from app.core.security import decode_token
from app.models.lead_request import LeadRequest
from app.models.user import User
from app.schemas.leads import LeadCreateIn, LeadCreateOut

router = APIRouter(prefix="/leads", tags=["leads"])


def _resolve_optional_user(
    creds: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> Optional[User]:
    if creds is None or not creds.credentials:
        return None
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        return None
    if payload.get("type") != "access":
        return None
    email = payload.get("sub")
    if not email:
        return None
    return db.query(User).filter(User.email == email).first()


@router.post("", response_model=LeadCreateOut)
def create_lead(
    payload: LeadCreateIn,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    user = _resolve_optional_user(creds, db)

    vin = (payload.vin or "").strip().upper() or None
    make = (payload.make or "").strip() or None
    model = (payload.model or "").strip() or None
    trim = (payload.trim or "").strip() or None
    vehicle = (payload.vehicle or "").strip() or None
    if not vehicle:
        vehicle = " ".join(str(part).strip() for part in [payload.year, make, model, trim] if part).strip() or None

    row = LeadRequest(
        user_id=int(user.id) if user else None,
        vin=vin,
        year=payload.year,
        make=make,
        model=model,
        trim=trim,
        vehicle=vehicle,
        name=payload.name.strip(),
        email=str(payload.email).strip().lower(),
        phone=payload.phone.strip(),
        notes=(payload.notes or "").strip() or None,
        source=(payload.source or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return LeadCreateOut(saved=True, lead_id=int(row.id))
