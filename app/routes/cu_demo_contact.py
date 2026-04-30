from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_role
from app.models.cu_demo_contact import CuDemoContact
from app.services.cu_demo_contact_notify import send_cu_demo_contact_email_task
from app.services.cu_demo_contact_rate_limit import enforce_cu_demo_contact_rate_limit

router = APIRouter(tags=["cu_demo_contact"])


class CuDemoContactIn(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    cu_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=80)
    message: Optional[str] = Field(None, max_length=8000)


@router.post("/public/cu-demo-contact")
def public_submit_cu_demo_contact(
    request: Request,
    payload: CuDemoContactIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    enforce_cu_demo_contact_rate_limit(request)
    row = CuDemoContact(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        cu_name=payload.cu_name.strip(),
        email=str(payload.email).strip().lower(),
        phone=(payload.phone or "").strip() or None,
        message=(payload.message or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background_tasks.add_task(send_cu_demo_contact_email_task, int(row.id))
    return {"ok": True, "id": int(row.id)}


@router.get("/admin/cu-demo-contacts", response_model=dict)
def admin_list_cu_demo_contacts(
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    rows: List[CuDemoContact] = (
        db.query(CuDemoContact).order_by(CuDemoContact.created_at.desc()).limit(limit).all()
    )
    return {
        "items": [
            {
                "id": int(r.id),
                "first_name": r.first_name,
                "last_name": r.last_name,
                "cu_name": r.cu_name,
                "email": r.email,
                "phone": r.phone,
                "message": r.message,
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in rows
        ]
    }
