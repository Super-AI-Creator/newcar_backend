from typing import List
import time

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.testimonial import Testimonial
from app.services.response_cache import get_shared_json, set_shared_json

router = APIRouter(prefix="/testimonials", tags=["testimonials"])
_TESTIMONIALS_CACHE: tuple[float, List[dict]] | None = None
_TESTIMONIALS_CACHE_TTL_SECONDS = 60.0
_EDGE_CACHE_HEADER_VALUE = "public, s-maxage=600, stale-while-revalidate=3600"
_TESTIMONIALS_SHARED_CACHE_NAMESPACE = "testimonials"
_TESTIMONIALS_SHARED_CACHE_KEY = "all"
_TESTIMONIALS_SHARED_CACHE_TTL_SECONDS = 600


@router.get("", response_model=List[dict])
def list_testimonials(response: Response, db: Session = Depends(get_db)):
    """Return testimonials from database, ordered by sort_order then id."""
    response.headers["Cache-Control"] = _EDGE_CACHE_HEADER_VALUE
    global _TESTIMONIALS_CACHE
    now = time.time()
    if _TESTIMONIALS_CACHE:
        expires_at, payload = _TESTIMONIALS_CACHE
        if now < expires_at:
            return payload
    shared_cached = get_shared_json(_TESTIMONIALS_SHARED_CACHE_NAMESPACE, _TESTIMONIALS_SHARED_CACHE_KEY)
    if isinstance(shared_cached, list):
        _TESTIMONIALS_CACHE = (now + _TESTIMONIALS_CACHE_TTL_SECONDS, shared_cached)
        return shared_cached

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
    set_shared_json(
        _TESTIMONIALS_SHARED_CACHE_NAMESPACE,
        _TESTIMONIALS_SHARED_CACHE_KEY,
        payload,
        _TESTIMONIALS_SHARED_CACHE_TTL_SECONDS,
    )
    return payload
