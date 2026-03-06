from datetime import datetime
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.document_submission import DocumentSubmission
from app.models.user import User

router = APIRouter(prefix="/docs", tags=["docs"])

MAX_DOC_BYTES = 8 * 1024 * 1024
ALLOWED_DOC_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _sanitize_filename(name: Optional[str], fallback: str) -> str:
    raw = (name or fallback).strip() or fallback
    return raw.replace("\\", "_").replace("/", "_")


def _serialize_doc_submission(
    row: DocumentSubmission,
    customer: Optional[User] = None,
    reviewer: Optional[User] = None,
) -> dict:
    return {
        "id": int(row.id),
        "user_id": int(row.user_id),
        "vin": row.vin,
        "status": row.status,
        "broker_note": row.broker_note,
        "reviewed_by_user_id": int(row.reviewed_by_user_id) if row.reviewed_by_user_id is not None else None,
        "reviewed_by_name": reviewer.name if reviewer else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "customer_name": customer.name if customer else None,
        "customer_email": customer.email if customer else None,
        "customer_phone": customer.phone if customer else None,
        "drivers_license_filename": row.drivers_license_filename,
        "insurance_filename": row.insurance_filename,
    }


@router.post("/forward")
async def forward_docs(
    drivers_license: UploadFile = File(...),
    insurance: UploadFile = File(...),
    vin: Optional[str] = Form(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dl_bytes = await drivers_license.read()
    ins_bytes = await insurance.read()

    if not dl_bytes or not ins_bytes:
        raise HTTPException(status_code=400, detail="Both documents are required.")
    if len(dl_bytes) > MAX_DOC_BYTES or len(ins_bytes) > MAX_DOC_BYTES:
        raise HTTPException(status_code=413, detail="Each file must be 8MB or smaller.")

    dl_type = (drivers_license.content_type or "application/octet-stream").lower()
    ins_type = (insurance.content_type or "application/octet-stream").lower()
    if dl_type not in ALLOWED_DOC_MIME_TYPES or ins_type not in ALLOWED_DOC_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload PDF or image files only.")

    row = DocumentSubmission(
        user_id=user.id,
        vin=(vin or "").strip().upper() or None,
        status="submitted",
        drivers_license_filename=_sanitize_filename(drivers_license.filename, "drivers_license"),
        drivers_license_content_type=dl_type,
        drivers_license_bytes=dl_bytes,
        insurance_filename=_sanitize_filename(insurance.filename, "insurance"),
        insurance_content_type=ins_type,
        insurance_bytes=ins_bytes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "stored", "id": int(row.id)}


@router.get("/submissions")
def list_doc_submissions(
    status_filter: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "admin")),
):
    _ = user
    query = db.query(DocumentSubmission).order_by(DocumentSubmission.created_at.desc())
    if status_filter:
        query = query.filter(DocumentSubmission.status == status_filter.strip().lower())
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(DocumentSubmission.vin.ilike(needle))

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    user_ids = {int(row.user_id) for row in rows}
    reviewer_ids = {int(row.reviewed_by_user_id) for row in rows if row.reviewed_by_user_id is not None}
    users = db.query(User).filter(User.id.in_(list(user_ids | reviewer_ids))).all() if (user_ids or reviewer_ids) else []
    user_map = {int(item.id): item for item in users}

    items = [
        _serialize_doc_submission(
            row,
            customer=user_map.get(int(row.user_id)),
            reviewer=user_map.get(int(row.reviewed_by_user_id)) if row.reviewed_by_user_id is not None else None,
        )
        for row in rows
    ]
    return {"items": items, "total": total}


@router.get("/mine")
def list_my_doc_submissions(
    vin: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = (
        db.query(DocumentSubmission)
        .filter(DocumentSubmission.user_id == user.id)
        .order_by(DocumentSubmission.created_at.desc())
    )
    if vin and vin.strip():
        query = query.filter(DocumentSubmission.vin == vin.strip().upper())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [_serialize_doc_submission(row, customer=user) for row in rows]
    return {"items": items, "total": total}


@router.patch("/submissions/{submission_id}")
def update_doc_submission(
    submission_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "admin")),
):
    row = db.query(DocumentSubmission).filter(DocumentSubmission.id == submission_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document submission not found")

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
    customer = db.query(User).filter(User.id == row.user_id).first()
    reviewer = db.query(User).filter(User.id == row.reviewed_by_user_id).first() if row.reviewed_by_user_id is not None else None
    return _serialize_doc_submission(row, customer=customer, reviewer=reviewer)


@router.get("/submissions/{submission_id}/file/{kind}")
def download_doc_file(
    submission_id: int,
    kind: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "admin")),
):
    _ = user
    row = db.query(DocumentSubmission).filter(DocumentSubmission.id == submission_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document submission not found")

    normalized_kind = (kind or "").strip().lower()
    if normalized_kind == "drivers_license":
        content = row.drivers_license_bytes
        filename = row.drivers_license_filename or "drivers_license"
        content_type = row.drivers_license_content_type or "application/octet-stream"
    elif normalized_kind == "insurance":
        content = row.insurance_bytes
        filename = row.insurance_filename or "insurance"
        content_type = row.insurance_content_type or "application/octet-stream"
    else:
        raise HTTPException(status_code=400, detail="Invalid file kind")

    if not content:
        raise HTTPException(status_code=404, detail="File not found")

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(content), media_type=content_type, headers=headers)
