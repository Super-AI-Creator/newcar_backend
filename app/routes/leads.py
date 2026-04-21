from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db, security
from app.core.security import decode_token
from app.models.lead_request import LeadRequest
from app.models.user import User
from app.schemas.leads import LeadCreateIn, LeadCreateOut
from app.services.cloudinary import CloudinaryUploadError, cloudinary_is_configured, upload_image_to_cloudinary
from app.services.lead_delivery import build_lead_webhook_payload, is_lead_webhook_enabled, process_new_lead_integrations

router = APIRouter(prefix="/leads", tags=["leads"])

MAX_TRADEIN_PHOTO_BYTES = 8 * 1024 * 1024
_TRADEIN_PHOTO_MIME_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_TRADEIN_PHOTO_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "trade-in"


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


@router.post("/upload-photo")
async def upload_trade_in_photo(file: UploadFile = File(...)):
    content_type = (file.content_type or "application/octet-stream").lower()
    suffix = _TRADEIN_PHOTO_MIME_SUFFIX.get(content_type)
    if not suffix:
        raise HTTPException(status_code=415, detail="Unsupported image type. Use JPG, PNG, or WEBP.")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Image file is required.")
    if len(payload) > MAX_TRADEIN_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 8MB or smaller.")

    source_filename = (file.filename or "").strip() or f"trade_in{suffix}"

    if cloudinary_is_configured():
        try:
            uploaded_url = await upload_image_to_cloudinary(
                payload,
                filename=source_filename,
                content_type=content_type,
                folder=(settings.cloudinary_upload_folder or "trade-in"),
            )
        except CloudinaryUploadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "url": uploaded_url,
            "filename": source_filename,
            "content_type": content_type,
            "size_bytes": len(payload),
            "provider": "cloudinary",
        }

    _TRADEIN_PHOTO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}{suffix}"
    path = _TRADEIN_PHOTO_UPLOAD_DIR / filename
    path.write_bytes(payload)

    return {
        "url": f"/uploads/trade-in/{filename}",
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(payload),
        "provider": "local",
    }


@router.post("", response_model=LeadCreateOut)
def create_lead(
    payload: LeadCreateIn,
    background_tasks: BackgroundTasks,
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
        webhook_status="pending" if is_lead_webhook_enabled() else "skipped",
        webhook_attempts=0,
        webhook_last_error=None if is_lead_webhook_enabled() else "LEAD_WEBHOOK_URL is not configured",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background_tasks.add_task(process_new_lead_integrations, build_lead_webhook_payload(row))

    return LeadCreateOut(saved=True, lead_id=int(row.id))
