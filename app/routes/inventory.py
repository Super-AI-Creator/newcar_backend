from __future__ import annotations

import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_db
from app.models.model_score import ModelScore
from app.models.offer_override import OfferOverride
from app.models.user import User
from app.schemas.inventory import InventoryItem, InventorySearchResponse, OfferOverrideOut, ModelScoreOut
from app.services.legacy_tables import build_inventory_count_query, build_inventory_query, serialize_photos
from app.services.offers import apply_offer_visibility

router = APIRouter(prefix="/inventory", tags=["inventory"])
_SEARCH_CACHE: dict[str, tuple[float, dict]] = {}
_SEARCH_CACHE_TTL_SECONDS = 12.0
_SEARCH_CACHE_MAX_ENTRIES = 256


def _serialize_details(raw):
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _load_offer_map(db: Session, vins):
    if not vins:
        return {}
    offers = db.query(OfferOverride).filter(OfferOverride.vin.in_(vins)).all()
    return {offer.vin: offer for offer in offers}


def _normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _dealer_phone_by_email(db: Session, emails: set[str]) -> dict[str, str]:
    if not emails:
        return {}
    rows = (
        db.query(User.email, User.phone)
        .filter(func.lower(User.email).in_(list(emails)))
        .all()
    )
    out: dict[str, str] = {}
    for email, phone in rows:
        normalized = _normalize_email(email)
        if normalized and phone:
            out[normalized] = phone
    return out


def _load_score_maps(db: Session, rows):
    keys = {
        (
            r._mapping.get("make"),
            r._mapping.get("model"),
            r._mapping.get("trim"),
            r._mapping.get("year"),
        )
        for r in rows
        if r._mapping.get("make") and r._mapping.get("model")
    }
    if not keys:
        return {}, {}, {}, {}

    makes = sorted({k[0] for k in keys})
    models = sorted({k[1] for k in keys})
    scores = (
        db.query(ModelScore)
        .filter(ModelScore.make.in_(makes), ModelScore.model.in_(models))
        .all()
    )

    exact_map = {}
    trim_fallback_map = {}
    year_fallback_map = {}
    full_fallback_map = {}
    for s in scores:
        if s.trim is not None and s.year is not None:
            exact_map[(s.make, s.model, s.trim, s.year)] = s
        elif s.trim is None and s.year is not None:
            trim_fallback_map[(s.make, s.model, s.year)] = s
        elif s.trim is not None and s.year is None:
            year_fallback_map[(s.make, s.model, s.trim)] = s
        else:
            full_fallback_map[(s.make, s.model)] = s
    return exact_map, trim_fallback_map, year_fallback_map, full_fallback_map


def _cache_key_from_params(**kwargs) -> str:
    parts = []
    for key in sorted(kwargs.keys()):
        parts.append(f"{key}={kwargs[key]}")
    return "|".join(parts)


def _cache_get(key: str):
    now = time.time()
    cached = _SEARCH_CACHE.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if now >= expires_at:
        _SEARCH_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict):
    now = time.time()
    _SEARCH_CACHE[key] = (now + _SEARCH_CACHE_TTL_SECONDS, payload)
    # Simple bounded cache cleanup.
    if len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX_ENTRIES:
        expired_keys = [k for k, (expires_at, _) in _SEARCH_CACHE.items() if expires_at <= now]
        for k in expired_keys:
            _SEARCH_CACHE.pop(k, None)
        if len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(_SEARCH_CACHE.items(), key=lambda item: item[1][0])[0]
            _SEARCH_CACHE.pop(oldest_key, None)


@router.get("/search", response_model=InventorySearchResponse, response_model_exclude_none=True)
def search_inventory(
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
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    cache_key = _cache_key_from_params(
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
        sort=sort,
        page=page,
        page_size=page_size,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return InventorySearchResponse(**cached)

    filters = {
        "make": make,
        "model": model,
        "trim": trim,
        "year": year,
        "vehicle_type": vehicle_type,
        "max_price": max_price,
        "max_mileage": max_mileage,
        "condition": condition,
    }
    base_query = build_inventory_query(engine, filters)
    if offers_only:
        vin_col = base_query.selected_columns.get("vin")
        if vin_col is not None:
            base_query = base_query.where(vin_col.in_(select(OfferOverride.vin)))
    if max_payment is not None and max_payment > 0:
        fetch_size = min(500, max(page_size * 10, 100))
        offset = 0
    else:
        fetch_size = page_size
        offset = (page - 1) * page_size

    sort_col = base_query.selected_columns.get("sort_price")
    if sort_col is None:
        sort_col = base_query.selected_columns.get("msrp")
    if sort == "price_asc" and sort_col is not None:
        base_query = base_query.order_by(sort_col.asc())
    elif sort == "price_desc" and sort_col is not None:
        base_query = base_query.order_by(sort_col.desc())

    if max_payment is None or max_payment <= 0:
        total = db.execute(build_inventory_count_query(engine, filters)).scalar() or 0
    else:
        total = None

    rows = db.execute(base_query.limit(fetch_size).offset(offset)).fetchall()
    vins = [r._mapping.get("vin") for r in rows if r._mapping.get("vin")]
    offer_map = _load_offer_map(db, vins)
    dealer_emails = {
        email
        for email in (
            _normalize_email(r._mapping.get("dealer_email")) for r in rows
        )
        if email
    }
    dealer_phone_map = _dealer_phone_by_email(db, dealer_emails)
    exact_score_map, trim_fallback_score_map, year_fallback_score_map, full_fallback_score_map = _load_score_maps(db, rows)

    items = []
    for row in rows:
        mapping = row._mapping
        vin = mapping.get("vin")
        row_vehicle_type = (mapping.get("vehicle_type") or "").lower() or None
        dealer_email = _normalize_email(mapping.get("dealer_email"))
        dealer_phone = mapping.get("dealer_phone") or (dealer_phone_map.get(dealer_email) if dealer_email else None)
        offer = offer_map.get(vin)
        offer_out = apply_offer_visibility(offer, row_vehicle_type)
        score = None
        make_value = mapping.get("make")
        model_value = mapping.get("model")
        trim_value = mapping.get("trim")
        year_value = mapping.get("year")
        if make_value and model_value:
            score = exact_score_map.get((make_value, model_value, trim_value, year_value))
            if not score:
                score = year_fallback_score_map.get((make_value, model_value, trim_value))
            if not score:
                score = trim_fallback_score_map.get((make_value, model_value, year_value))
            if not score:
                score = full_fallback_score_map.get((make_value, model_value))
        items.append(
            InventoryItem(
                vin=vin,
                vehicle_type=row_vehicle_type,
                year=mapping.get("year"),
                make=mapping.get("make"),
                model=mapping.get("model"),
                trim=mapping.get("trim"),
                msrp=float(mapping.get("msrp")) if mapping.get("msrp") is not None else None,
                listed_price=float(mapping.get("listed_price")) if mapping.get("listed_price") is not None else None,
                mileage=mapping.get("mileage"),
                condition=str(mapping.get("condition")).lower() if mapping.get("condition") else None,
                details=_serialize_details(mapping.get("details")),
                photos=serialize_photos(mapping.get("photos")),
                last_seen_at=str(mapping.get("last_seen_at")) if mapping.get("last_seen_at") else None,
                dealer_name=mapping.get("dealer_name"),
                dealer_phone=dealer_phone,
                listing_url=mapping.get("listing_url"),
                carfax_url=mapping.get("carfax_url"),
                offer=OfferOverrideOut(**offer_out) if offer_out else None,
                model_scores=ModelScoreOut(
                    design=score.design,
                    performance=score.performance,
                    technology=score.technology,
                    practicality=score.practicality,
                    future_value=score.future_value,
                )
                if score
                else None,
            )
        )

    if max_payment is not None and max_payment > 0:
        def _monthly_ok(item: InventoryItem) -> bool:
            if (item.vehicle_type or "").lower() != "new":
                return True
            monthly = item.offer and getattr(item.offer, "monthly_payment", None)
            if monthly is None:
                return True
            return float(monthly) <= max_payment
        items = [i for i in items if _monthly_ok(i)]
        total = len(items)
        start = (page - 1) * page_size
        items = items[start : start + page_size]

    response = InventorySearchResponse(items=items, page=page, page_size=page_size, total=total or 0)
    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    _cache_set(cache_key, payload)
    return response


@router.get("/{vin}", response_model=InventoryItem, response_model_exclude_none=True)
def get_inventory_item(
    vin: str,
    db: Session = Depends(get_db),
):
    query = build_inventory_query(engine, {"vin": vin})
    row = db.execute(query).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="VIN not found")

    mapping = row._mapping
    row_vehicle_type = (mapping.get("vehicle_type") or "").lower() or None
    dealer_email = _normalize_email(mapping.get("dealer_email"))
    dealer_phone = mapping.get("dealer_phone")
    if not dealer_phone and dealer_email:
        dealer_phone = _dealer_phone_by_email(db, {dealer_email}).get(dealer_email)
    offer = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
    offer_out = apply_offer_visibility(offer, row_vehicle_type)

    score = None
    if mapping.get("make") and mapping.get("model"):
        make_value = mapping.get("make")
        model_value = mapping.get("model")
        trim_value = mapping.get("trim")
        year_value = mapping.get("year")
        score = (
            db.query(ModelScore)
            .filter(
                ModelScore.make == make_value,
                ModelScore.model == model_value,
                ModelScore.trim == trim_value,
                ModelScore.year == year_value,
            )
            .first()
        )
        if not score:
            score = (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim == trim_value,
                    ModelScore.year.is_(None),
                )
                .first()
            )
        if not score:
            score = (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim.is_(None),
                    ModelScore.year == year_value,
                )
                .first()
            )
        if not score:
            score = (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim.is_(None),
                    ModelScore.year.is_(None),
                )
                .first()
            )

    return InventoryItem(
        vin=vin,
        vehicle_type=row_vehicle_type,
        year=mapping.get("year"),
        make=mapping.get("make"),
        model=mapping.get("model"),
        trim=mapping.get("trim"),
        msrp=float(mapping.get("msrp")) if mapping.get("msrp") is not None else None,
        listed_price=float(mapping.get("listed_price")) if mapping.get("listed_price") is not None else None,
        mileage=mapping.get("mileage"),
        condition=str(mapping.get("condition")).lower() if mapping.get("condition") else None,
        details=_serialize_details(mapping.get("details")),
        photos=serialize_photos(mapping.get("photos")),
        last_seen_at=str(mapping.get("last_seen_at")) if mapping.get("last_seen_at") else None,
        dealer_name=mapping.get("dealer_name"),
        dealer_phone=dealer_phone,
        listing_url=mapping.get("listing_url"),
        carfax_url=mapping.get("carfax_url"),
        offer=OfferOverrideOut(**offer_out) if offer_out else None,
        model_scores=ModelScoreOut(
            design=score.design,
            performance=score.performance,
            technology=score.technology,
            practicality=score.practicality,
            future_value=score.future_value,
        )
        if score
        else None,
    )
