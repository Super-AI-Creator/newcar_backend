import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.seo_page_setting import SeoPageSetting

router = APIRouter(prefix="/seo", tags=["seo"])

_SEO_PAGE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalize_page_key(page_key: str) -> str:
    normalized = (page_key or "").strip().lower()
    if not _SEO_PAGE_KEY_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Invalid page key.")
    return normalized


def _parse_json_ld(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _serialize(row: SeoPageSetting) -> dict:
    return {
        "page_key": row.page_key,
        "title": row.title,
        "description": row.description,
        "keywords": row.keywords,
        "canonical_url": row.canonical_url,
        "og_title": row.og_title,
        "og_description": row.og_description,
        "og_image_url": row.og_image_url,
        "robots": row.robots,
        "json_ld": _parse_json_ld(row.json_ld_text),
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@router.get("/pages/{page_key}")
def get_page_seo(page_key: str, db: Session = Depends(get_db)):
    normalized_key = _normalize_page_key(page_key)
    row = (
        db.query(SeoPageSetting)
        .filter(SeoPageSetting.page_key == normalized_key, SeoPageSetting.is_active == True)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="SEO setting not found.")
    return _serialize(row)
