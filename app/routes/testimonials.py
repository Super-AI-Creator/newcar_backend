from typing import List
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.testimonial import Testimonial

router = APIRouter(prefix="/testimonials", tags=["testimonials"])
_TESTIMONIALS_CACHE: tuple[float, List[dict]] | None = None
_TESTIMONIALS_CACHE_TTL_SECONDS = 60.0


@router.get("", response_model=List[dict])
def list_testimonials(db: Session = Depends(get_db)):
    """Return testimonials from database, ordered by sort_order then id."""
    global _TESTIMONIALS_CACHE
    now = time.time()
    if _TESTIMONIALS_CACHE:
        expires_at, payload = _TESTIMONIALS_CACHE
        if now < expires_at:
            return payload

    rows = (
        db.query(Testimonial)
        .order_by(Testimonial.sort_order.asc(), Testimonial.id.asc())
        .all()
    )
    payload = [
        {
            "id": str(row.id),
            "title": row.title,
            "quote": row.quote,
            "author": row.author,
            "image_url": getattr(row, "image_url", None),
        }
        for row in rows
    ]
    _TESTIMONIALS_CACHE = (now + _TESTIMONIALS_CACHE_TTL_SECONDS, payload)
    return payload
