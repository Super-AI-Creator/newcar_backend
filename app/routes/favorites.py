from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.favorite import Favorite
from app.schemas.misc import FavoriteOut
from app.services.cu_member_scope import resolve_member_scope_user_id

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=list[FavoriteOut])
def list_favorites(
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    rows = db.query(Favorite).filter(Favorite.user_id == scoped_user_id).order_by(Favorite.created_at.desc()).all()
    return [FavoriteOut(vin=row.vin, created_at=str(row.created_at)) for row in rows]


@router.post("/{vin}")
def add_favorite(
    vin: str,
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    existing = db.query(Favorite).filter(Favorite.user_id == scoped_user_id, Favorite.vin == vin).first()
    if existing:
        return {"status": "exists"}
    fav = Favorite(user_id=scoped_user_id, vin=vin)
    db.add(fav)
    db.commit()
    return {"status": "added"}


@router.delete("/{vin}")
def remove_favorite(
    vin: str,
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    existing = db.query(Favorite).filter(Favorite.user_id == scoped_user_id, Favorite.vin == vin).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(existing)
    db.commit()
    return {"status": "removed"}
