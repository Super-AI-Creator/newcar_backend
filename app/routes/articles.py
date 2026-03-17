"""Public articles API (no auth)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.article import Article

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("")
def list_articles(db: Session = Depends(get_db)):
    """Public list of articles (title, description, slug, date only)."""
    rows = db.query(Article).order_by(Article.date.desc(), Article.id.desc()).all()
    return {
        "items": [
            {
                "id": int(row.id),
                "title": row.title,
                "description": row.description,
                "slug": row.slug,
                "date": row.date,
            }
            for row in rows
        ]
    }


@router.get("/by-slug/{slug}")
def get_article_by_slug(slug: str, db: Session = Depends(get_db)):
    """Public get one article by slug (full content)."""
    row = db.query(Article).filter(Article.slug == slug).first()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")
    return {
        "id": int(row.id),
        "title": row.title,
        "description": row.description,
        "slug": row.slug,
        "date": row.date,
        "content": row.content,
    }
