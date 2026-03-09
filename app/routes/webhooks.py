from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db
from app.services.sheets_runner import run_sheets_sync_with_lock


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/sheets-changed")
def sheets_changed(
    db: Session = Depends(get_db),
    webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    expected_secret = (settings.sheets_webhook_secret or "").strip()
    if not expected_secret:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured.")

    provided_secret = (webhook_secret or "").strip()
    if not provided_secret or provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    result = run_sheets_sync_with_lock(
        db,
        wait_seconds=settings.sheets_webhook_lock_wait_seconds,
    )
    if result.get("locked"):
        return JSONResponse(status_code=202, content=result)
    return result

