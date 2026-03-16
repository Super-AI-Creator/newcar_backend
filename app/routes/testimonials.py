from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.testimonial import Testimonial

router = APIRouter(prefix="/testimonials", tags=["testimonials"])


@router.get("", response_model=List[dict])
def list_testimonials(db: Session = Depends(get_db)):
    """Return testimonials from database, ordered by sort_order then id."""
    rows = (
        db.query(Testimonial)
        .order_by(Testimonial.sort_order.asc(), Testimonial.id.asc())
        .all()
    )
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "quote": row.quote,
            "author": row.author,
            "image_url": getattr(row, "image_url", None),
        }
        for row in rows
    ]
