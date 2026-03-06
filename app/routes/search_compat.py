from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.routes.inventory import search_inventory
from app.schemas.inventory import InventorySearchResponse

router = APIRouter(tags=["search-compat"])


@router.get("/search", response_model=InventorySearchResponse, response_model_exclude_none=True)
def search_compat(
    make: Optional[str] = None,
    model: Optional[str] = None,
    trim: Optional[str] = None,
    year: Optional[int] = None,
    vehicle_type: str = Query("all", pattern="^(new|used|all)$"),
    max_price: Optional[float] = None,
    max_payment: Optional[float] = None,
    max_mileage: Optional[int] = None,
    condition: str = Query("all", pattern="^(used|cpo|all)$"),
    offers_only: bool = Query(False),
    sort: Optional[str] = None,
    mode: Optional[str] = None,
    estimate: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    mapped_sort = sort
    if sort == "best_deal":
        mapped_sort = None
    elif sort in {"price", "price_low", "price_asc"}:
        mapped_sort = "price_asc"
    elif sort in {"price_high", "price_desc"}:
        mapped_sort = "price_desc"

    # `mode` and `estimate` are accepted for frontend compatibility.
    _ = mode
    _ = estimate

    return search_inventory(
        make=make,
        model=model,
        trim=trim,
        year=year,
        vehicle_type=vehicle_type,
        max_price=max_price,
        max_payment=max_payment,
        max_mileage=max_mileage,
        condition=condition,
        offers_only=offers_only,
        sort=mapped_sort,
        page=page,
        page_size=page_size,
        db=db,
    )
