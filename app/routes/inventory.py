from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_db
from app.models.model_score import ModelScore
from app.models.offer_override import OfferOverride
from app.models.homepage_featured_vehicle import HomepageFeaturedVehicle
from app.models.manual_vehicle import ManualVehicle
from app.models.user import User
from app.schemas.inventory import InventoryItem, InventorySearchResponse, OfferOverrideOut, ModelScoreOut
from app.services.legacy_tables import build_inventory_count_query, build_inventory_query, serialize_photos
from app.services.make_normalization import canonicalize_make
from app.services.offers import apply_offer_visibility

router = APIRouter(prefix="/inventory", tags=["inventory"])
_SEARCH_CACHE: dict[str, tuple[float, dict]] = {}
_SEARCH_CACHE_TTL_SECONDS = 12.0
_SEARCH_CACHE_MAX_ENTRIES = 256
_FILTERS_CACHE: dict[str, tuple[float, dict]] = {}
_FILTERS_CACHE_TTL_SECONDS = 30.0
_FILTERS_CACHE_MAX_ENTRIES = 64
_MONTH_KEY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_MAX_HOMEPAGE_FEATURED_VEHICLES = 6
_HOMEPAGE_SPECIALS_CACHE: dict[str, tuple[float, dict]] = {}
_HOMEPAGE_SPECIALS_CACHE_TTL_SECONDS = 60.0


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


def _normalize_ymm_key(year: Optional[int], make: Optional[str], model: Optional[str]):
    if year is None:
        return None
    make_value = (make or "").strip().lower()
    model_value = (model or "").strip().lower()
    if not make_value or not model_value:
        return None
    return int(year), make_value, model_value


def _offer_priority(offer: OfferOverride):
    source_value = offer.source.value if hasattr(offer.source, "value") else str(offer.source or "")
    source_rank = {"broker": 3, "sheet": 2, "dealer": 1}.get(str(source_value).lower(), 0)
    updated_rank = offer.updated_at.timestamp() if getattr(offer, "updated_at", None) else 0
    return (
        1 if offer.monthly_payment is not None else 0,
        1 if offer.discounted_price is not None else 0,
        source_rank,
        updated_rank,
    )


def _load_offer_ymm_map(db: Session, keys: set[tuple[int, str, str]]):
    if not keys:
        return {}

    offers = db.query(OfferOverride).all()
    offer_by_vin = {str(row.vin).strip().upper(): row for row in offers if row.vin}
    offer_vins = sorted(offer_by_vin.keys())
    if not offer_vins:
        return {}

    matched_keys: dict[tuple[int, str, str], OfferOverride] = {}

    inventory_query = build_inventory_query(engine, {"vehicle_type": "all"})
    vin_col = inventory_query.selected_columns.get("vin")
    rows = []
    if vin_col is not None:
        rows = db.execute(inventory_query.where(vin_col.in_(offer_vins))).fetchall()

    matched_vins: set[str] = set()
    for row in rows:
        mapping = row._mapping
        vin = str(mapping.get("vin") or "").strip().upper()
        if not vin:
            continue
        matched_vins.add(vin)
        offer = offer_by_vin.get(vin)
        if not offer:
            continue
        key = _normalize_ymm_key(mapping.get("year"), mapping.get("make"), mapping.get("model"))
        if not key or key not in keys:
            continue
        current = matched_keys.get(key)
        if current is None or _offer_priority(offer) > _offer_priority(current):
            matched_keys[key] = offer

    missing_vins = [vin for vin in offer_vins if vin not in matched_vins]
    if missing_vins:
        manual_rows = (
            db.query(ManualVehicle)
            .filter(ManualVehicle.vin.in_(missing_vins), ManualVehicle.is_active == True)
            .all()
        )
        for row in manual_rows:
            vin = str(row.vin or "").strip().upper()
            if not vin:
                continue
            offer = offer_by_vin.get(vin)
            if not offer:
                continue
            key = _normalize_ymm_key(row.year, row.make, row.model)
            if not key or key not in keys:
                continue
            current = matched_keys.get(key)
            if current is None or _offer_priority(offer) > _offer_priority(current):
                matched_keys[key] = offer

    return matched_keys


def _resolve_offer_for_vehicle(
    *,
    vin: Optional[str],
    year: Optional[int],
    make: Optional[str],
    model: Optional[str],
    offer_map: dict[str, OfferOverride],
    ymm_offer_map: dict[tuple[int, str, str], OfferOverride],
):
    normalized_vin = str(vin or "").strip().upper()
    if normalized_vin and normalized_vin in offer_map:
        return offer_map.get(normalized_vin)
    key = _normalize_ymm_key(year, make, model)
    if key:
        return ymm_offer_map.get(key)
    return None


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


def _filters_cache_get(key: str):
    now = time.time()
    cached = _FILTERS_CACHE.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if now >= expires_at:
        _FILTERS_CACHE.pop(key, None)
        return None
    return payload


def _filters_cache_set(key: str, payload: dict):
    now = time.time()
    _FILTERS_CACHE[key] = (now + _FILTERS_CACHE_TTL_SECONDS, payload)
    if len(_FILTERS_CACHE) > _FILTERS_CACHE_MAX_ENTRIES:
        expired_keys = [k for k, (expires_at, _) in _FILTERS_CACHE.items() if expires_at <= now]
        for k in expired_keys:
            _FILTERS_CACHE.pop(k, None)
        if len(_FILTERS_CACHE) > _FILTERS_CACHE_MAX_ENTRIES:
            oldest_key = min(_FILTERS_CACHE.items(), key=lambda item: item[1][0])[0]
            _FILTERS_CACHE.pop(oldest_key, None)


def _resolve_month_key(month: Optional[str]) -> str:
    candidate = (month or "").strip()
    if not candidate:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    if not _MONTH_KEY_RE.match(candidate):
        raise HTTPException(status_code=400, detail="month must be in YYYY-MM format.")
    return candidate


DEFAULT_HOMEPAGE_FEATURED_KEY = "default"


def _homepage_featured_key_for_read(db: Session) -> str:
    default_exists = (
        db.query(HomepageFeaturedVehicle.id)
        .filter(HomepageFeaturedVehicle.month_key == DEFAULT_HOMEPAGE_FEATURED_KEY)
        .first()
        is not None
    )
    if default_exists:
        return DEFAULT_HOMEPAGE_FEATURED_KEY

    latest = (
        db.query(HomepageFeaturedVehicle.month_key)
        .order_by(HomepageFeaturedVehicle.updated_at.desc(), HomepageFeaturedVehicle.id.desc())
        .first()
    )
    if latest and latest[0]:
        return str(latest[0])
    return DEFAULT_HOMEPAGE_FEATURED_KEY


def _manual_vehicle_photos(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    except Exception:
        return []
    return []


def _manual_vehicle_matches(
    row: ManualVehicle,
    *,
    make: Optional[str],
    model: Optional[str],
    trim: Optional[str],
    year: Optional[int],
    vehicle_type: str,
    max_price: Optional[float],
    max_mileage: Optional[int],
    condition: str,
) -> bool:
    if not row.is_active:
        return False
    if make and (row.make or "").strip().lower() != make.strip().lower():
        return False
    if model and (row.model or "").strip().lower() != model.strip().lower():
        return False
    if trim and (row.trim or "").strip().lower() != trim.strip().lower():
        return False
    if year is not None and (row.year is None or int(row.year) != int(year)):
        return False
    if vehicle_type in {"new", "used"} and (row.vehicle_type or "new").strip().lower() != vehicle_type:
        return False
    if condition in {"used", "cpo"} and (row.condition or "").strip().lower() != condition:
        return False
    price = row.listed_price if row.listed_price is not None else row.msrp
    if max_price is not None and price is not None and float(price) > float(max_price):
        return False
    if max_mileage is not None and row.mileage is not None and int(row.mileage) > int(max_mileage):
        return False
    return True


@router.get("/filters")
def inventory_filters(
    vehicle_type: str = Query("all", pattern="^(new|used|all)$"),
    offers_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    cache_key = f"vehicle_type={vehicle_type}|offers_only={offers_only}"
    cached = _filters_cache_get(cache_key)
    if cached is not None:
        return cached

    manual_rows = db.query(ManualVehicle).filter(ManualVehicle.is_active == True).all()
    base_query = build_inventory_query(engine, {"vehicle_type": vehicle_type})
    rows = db.execute(base_query).fetchall()

    vins = [str(row._mapping.get("vin") or "").strip().upper() for row in rows if row._mapping.get("vin")]
    offer_map = _load_offer_map(db, vins)
    ymm_keys_needed: set[tuple[int, str, str]] = set()
    for row in rows:
        mapping = row._mapping
        key = _normalize_ymm_key(mapping.get("year"), mapping.get("make"), mapping.get("model"))
        if key:
            ymm_keys_needed.add(key)
    for row in manual_rows:
        key = _normalize_ymm_key(row.year, row.make, row.model)
        if key:
            ymm_keys_needed.add(key)
    ymm_offer_map = _load_offer_ymm_map(db, ymm_keys_needed)

    models_by_make: dict[str, set[str]] = {}
    trims_by_make_model: dict[str, set[str]] = {}
    makes_set: set[str] = set()

    for row in rows:
        mapping = row._mapping
        make_value = mapping.get("make")
        model_value = mapping.get("model")
        trim_value = mapping.get("trim")
        if offers_only:
            offer = _resolve_offer_for_vehicle(
                vin=mapping.get("vin"),
                year=mapping.get("year"),
                make=make_value,
                model=model_value,
                offer_map=offer_map,
                ymm_offer_map=ymm_offer_map,
            )
            offer_out = apply_offer_visibility(offer, (mapping.get("vehicle_type") or "").strip().lower())
            if not offer_out:
                continue
        make_key = canonicalize_make(str(make_value)) if make_value is not None else None
        model_key = str(model_value).strip() if model_value is not None else ""
        if not make_key or not model_key:
            continue
        makes_set.add(make_key)
        models_by_make.setdefault(make_key, set()).add(model_key)
        if trim_value is not None and str(trim_value).strip():
            combo_key = f"{make_key}|||{model_key}"
            trims_by_make_model.setdefault(combo_key, set()).add(str(trim_value).strip())

    for row in manual_rows:
        vin = str(row.vin or "").strip().upper()
        row_vehicle_type = (row.vehicle_type or "new").strip().lower()
        if vehicle_type in {"new", "used"} and row_vehicle_type != vehicle_type:
            continue
        if offers_only:
            offer = _resolve_offer_for_vehicle(
                vin=vin,
                year=row.year,
                make=row.make,
                model=row.model,
                offer_map=offer_map,
                ymm_offer_map=ymm_offer_map,
            )
            if not apply_offer_visibility(offer, row_vehicle_type):
                continue
        make_value = (row.make or "").strip()
        model_value = (row.model or "").strip()
        trim_value = (row.trim or "").strip()
        if not make_value or not model_value:
            continue
        make_key = canonicalize_make(make_value)
        if not make_key:
            continue
        makes_set.add(make_key)
        models_by_make.setdefault(make_key, set()).add(model_value)
        if trim_value:
            combo_key = f"{make_key}|||{model_value}"
            trims_by_make_model.setdefault(combo_key, set()).add(trim_value)

    makes = sorted(makes_set)
    models_by_make_sorted = {key: sorted(values) for key, values in models_by_make.items()}
    trims_by_make_model_sorted = {key: sorted(values) for key, values in trims_by_make_model.items()}
    models = sorted({model for values in models_by_make_sorted.values() for model in values})
    trims = sorted({trim for values in trims_by_make_model_sorted.values() for trim in values})

    payload = {
        "makes": makes,
        "models": models,
        "trims": trims,
        "models_by_make": models_by_make_sorted,
        "trims_by_make_model": trims_by_make_model_sorted,
    }
    _filters_cache_set(cache_key, payload)
    return payload


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
        fetch_size = None
        offset = 0
    elif max_payment is not None and max_payment > 0:
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

    if offers_only:
        total = None
    elif max_payment is None or max_payment <= 0:
        total = db.execute(build_inventory_count_query(engine, filters)).scalar() or 0
    else:
        total = None

    if offers_only:
        # offers_only is typically used for "featured specials" style lists.
        # Always apply LIMIT/OFFSET; otherwise we accidentally fetch the entire inventory.
        rows = db.execute(base_query.limit(page_size).offset(offset)).fetchall()
    else:
        rows = db.execute(base_query.limit(fetch_size).offset(offset)).fetchall()
    vins = [r._mapping.get("vin") for r in rows if r._mapping.get("vin")]
    offer_map = _load_offer_map(db, vins)
    ymm_keys_needed: set[tuple[int, str, str]] = set()
    for row in rows:
        mapping = row._mapping
        key = _normalize_ymm_key(mapping.get("year"), mapping.get("make"), mapping.get("model"))
        if key:
            ymm_keys_needed.add(key)
    manual_rows = db.query(ManualVehicle).filter(ManualVehicle.is_active == True).all()
    for row in manual_rows:
        key = _normalize_ymm_key(row.year, row.make, row.model)
        if key:
            ymm_keys_needed.add(key)
    ymm_offer_map = _load_offer_ymm_map(db, ymm_keys_needed)
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
        offer = _resolve_offer_for_vehicle(
            vin=vin,
            year=mapping.get("year"),
            make=mapping.get("make"),
            model=mapping.get("model"),
            offer_map=offer_map,
            ymm_offer_map=ymm_offer_map,
        )
        offer_out = apply_offer_visibility(offer, row_vehicle_type)
        if offers_only and not offer_out:
            continue
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

    manual_vins = [str(row.vin).strip().upper() for row in manual_rows if row.vin]
    manual_offer_map = _load_offer_map(db, manual_vins)
    manual_items: list[InventoryItem] = []
    manual_match_count = 0
    for row in manual_rows:
        vin = str(row.vin or "").strip().upper()
        if not vin:
            continue
        if not _manual_vehicle_matches(
            row,
            make=make,
            model=model,
            trim=trim,
            year=year,
            vehicle_type=vehicle_type,
            max_price=max_price,
            max_mileage=max_mileage,
            condition=condition,
        ):
            continue
        offer = _resolve_offer_for_vehicle(
            vin=vin,
            year=row.year,
            make=row.make,
            model=row.model,
            offer_map=manual_offer_map,
            ymm_offer_map=ymm_offer_map,
        )
        offer_out = apply_offer_visibility(offer, (row.vehicle_type or "new").strip().lower())
        if offers_only and not offer_out:
            continue
        manual_match_count += 1
        if (max_payment is None or max_payment <= 0) and page != 1 and not offers_only:
            continue
        manual_items.append(
            InventoryItem(
                vin=vin,
                vehicle_type=(row.vehicle_type or "new").strip().lower(),
                year=row.year,
                make=row.make,
                model=row.model,
                trim=row.trim,
                msrp=float(row.msrp) if row.msrp is not None else None,
                listed_price=float(row.listed_price) if row.listed_price is not None else None,
                mileage=row.mileage,
                condition=(row.condition or "").strip().lower() or None,
                details=_serialize_details(row.details_json),
                photos=_manual_vehicle_photos(row.photos_json),
                last_seen_at=str(row.updated_at) if row.updated_at else None,
                dealer_name=row.dealer_name,
                dealer_phone=row.dealer_phone,
                listing_url=row.listing_url,
                carfax_url=row.carfax_url,
                offer=OfferOverrideOut(**offer_out) if offer_out else None,
                model_scores=None,
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
        if manual_items:
            manual_filtered = [i for i in manual_items if _monthly_ok(i)]
            if manual_filtered:
                existing_vins = {str(i.vin).strip().upper() for i in manual_filtered}
                items = manual_filtered + [i for i in items if str(i.vin).strip().upper() not in existing_vins]
        total = len(items)
        start = (page - 1) * page_size
        items = items[start : start + page_size]
    else:
        if total is not None:
            total += manual_match_count
        if manual_items:
            existing_vins = {str(i.vin).strip().upper() for i in manual_items}
            items = manual_items + [i for i in items if str(i.vin).strip().upper() not in existing_vins]
        if offers_only:
            total = len(items)
            start = (page - 1) * page_size
            items = items[start : start + page_size]
        else:
            items = items[:page_size]

    response = InventorySearchResponse(items=items, page=page, page_size=page_size, total=total or 0)
    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    _cache_set(cache_key, payload)
    return response


@router.get("/homepage-specials", response_model=InventorySearchResponse, response_model_exclude_none=True)
def homepage_specials(
    limit: int = Query(_MAX_HOMEPAGE_FEATURED_VEHICLES, ge=1, le=_MAX_HOMEPAGE_FEATURED_VEHICLES),
    db: Session = Depends(get_db),
):
    month_key = _homepage_featured_key_for_read(db)
    cache_key = f"limit={limit}|month={month_key}"
    now = time.time()
    cached = _HOMEPAGE_SPECIALS_CACHE.get(cache_key)
    if cached:
        expires_at, payload = cached
        if now < expires_at:
            return InventorySearchResponse(**payload)
    featured_rows = (
        db.query(HomepageFeaturedVehicle)
        .filter(HomepageFeaturedVehicle.month_key == month_key)
        .order_by(HomepageFeaturedVehicle.position.asc(), HomepageFeaturedVehicle.id.asc())
        .all()
    )
    items: list[InventoryItem] = []
    seen_vins: set[str] = set()

    # Fast path: if super-admin precomputed the landing-card payload, return it directly.
    cached_items_by_vin: dict[str, InventoryItem] = {}
    for r in featured_rows:
        vin = str(r.vin or "").strip().upper()
        if not vin:
            continue
        payload_raw = getattr(r, "card_payload_json", None)
        if not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
            cached_items_by_vin[vin] = InventoryItem.model_validate(payload)
        except Exception:
            # If cache is corrupted or old, fall back to live computation.
            continue

    missing_vins: list[str] = []
    seen_missing: set[str] = set()
    for r in featured_rows:
        vin = str(r.vin or "").strip().upper()
        if not vin or vin in seen_missing or vin in cached_items_by_vin:
            continue
        seen_missing.add(vin)
        missing_vins.append(vin)

    base_by_vin = {}
    if missing_vins:
        # Batch fetch base inventory rows for only the missing VINs.
        base_query = build_inventory_query(engine, {"vin_in": missing_vins})
        base_rows = db.execute(base_query).fetchall()
        base_by_vin = {str(r._mapping.get("vin") or "").strip().upper(): r._mapping for r in base_rows}

    for row in featured_rows:
        vin = str(row.vin or "").strip().upper()
        if not vin or vin in seen_vins:
            continue
        cached_item = cached_items_by_vin.get(vin)
        if cached_item:
            items.append(cached_item)
            seen_vins.add(vin)
            if len(items) >= limit:
                break
            continue
        mapping = base_by_vin.get(vin)
        if not mapping:
            # Fallback to existing per-vin loader if batch missed it.
            try:
                item = get_inventory_item(vin=vin, db=db)
            except HTTPException:
                continue
            items.append(item)
            seen_vins.add(vin)
            if len(items) >= limit:
                break
            continue

        # Reuse the same normalization logic as get_inventory_item for overrides/offers/scores.
        manual_override = (
            db.query(ManualVehicle)
            .filter(ManualVehicle.vin == vin, ManualVehicle.is_active == True)
            .first()
        )
        row_vehicle_type = (mapping.get("vehicle_type") or "").lower() or None
        effective_vehicle_type = (
            (manual_override.vehicle_type or "").strip().lower()
            if manual_override and manual_override.vehicle_type
            else row_vehicle_type
        )
        effective_year = manual_override.year if manual_override and manual_override.year is not None else mapping.get("year")
        effective_make = manual_override.make if manual_override and manual_override.make else mapping.get("make")
        effective_model = manual_override.model if manual_override and manual_override.model else mapping.get("model")
        effective_trim = manual_override.trim if manual_override and manual_override.trim else mapping.get("trim")
        effective_msrp = manual_override.msrp if manual_override and manual_override.msrp is not None else mapping.get("msrp")
        effective_listed_price = (
            manual_override.listed_price if manual_override and manual_override.listed_price is not None else mapping.get("listed_price")
        )
        effective_mileage = manual_override.mileage if manual_override and manual_override.mileage is not None else mapping.get("mileage")
        effective_condition = (
            (manual_override.condition or "").strip().lower()
            if manual_override and manual_override.condition
            else (str(mapping.get("condition")).lower() if mapping.get("condition") else None)
        )
        effective_details = manual_override.details_json if manual_override and manual_override.details_json else mapping.get("details")
        effective_photos = manual_override.photos_json if manual_override and manual_override.photos_json else mapping.get("photos")
        effective_dealer_name = manual_override.dealer_name if manual_override and manual_override.dealer_name else mapping.get("dealer_name")
        effective_listing_url = manual_override.listing_url if manual_override and manual_override.listing_url else mapping.get("listing_url")
        effective_carfax_url = manual_override.carfax_url if manual_override and manual_override.carfax_url else mapping.get("carfax_url")
        dealer_email = _normalize_email(mapping.get("dealer_email"))
        dealer_phone = manual_override.dealer_phone if manual_override and manual_override.dealer_phone else mapping.get("dealer_phone")
        if not dealer_phone and dealer_email:
            dealer_phone = _dealer_phone_by_email(db, {dealer_email}).get(dealer_email)
        offer = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
        if not offer:
            key = _normalize_ymm_key(effective_year, effective_make, effective_model)
            offer = _load_offer_ymm_map(db, {key} if key else set()).get(key) if key else None
        offer_out = apply_offer_visibility(offer, effective_vehicle_type)

        score = None
        if effective_make and effective_model:
            make_value = effective_make
            model_value = effective_model
            trim_value = effective_trim
            year_value = effective_year
            score = (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim == trim_value,
                    ModelScore.year == year_value,
                )
                .first()
            ) or (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim == trim_value,
                    ModelScore.year.is_(None),
                )
                .first()
            ) or (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim.is_(None),
                    ModelScore.year == year_value,
                )
                .first()
            ) or (
                db.query(ModelScore)
                .filter(
                    ModelScore.make == make_value,
                    ModelScore.model == model_value,
                    ModelScore.trim.is_(None),
                    ModelScore.year.is_(None),
                )
                .first()
            )

        items.append(
            InventoryItem(
                vin=vin,
                vehicle_type=effective_vehicle_type,
                year=effective_year,
                make=effective_make,
                model=effective_model,
                trim=effective_trim,
                msrp=float(effective_msrp) if effective_msrp is not None else None,
                listed_price=float(effective_listed_price) if effective_listed_price is not None else None,
                mileage=effective_mileage,
                condition=effective_condition,
                details=_serialize_details(effective_details),
                photos=_manual_vehicle_photos(effective_photos) if manual_override and manual_override.photos_json else serialize_photos(effective_photos),
                last_seen_at=str(mapping.get("last_seen_at")) if mapping.get("last_seen_at") else None,
                dealer_name=effective_dealer_name,
                dealer_phone=dealer_phone,
                listing_url=effective_listing_url,
                carfax_url=effective_carfax_url,
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
        seen_vins.add(vin)
        if len(items) >= limit:
            break

    # If we already have some cached cards, avoid the heavy search fallback.
    # This keeps the landing-page first load fast.
    if len(items) < limit and len(cached_items_by_vin) == 0:
        fallback = search_inventory(
            vehicle_type="new",
            offers_only=True,
            page=1,
            page_size=max(50, limit * 10),
            db=db,
        )
        for item in fallback.items:
            vin = str(item.vin or "").strip().upper()
            if not vin or vin in seen_vins:
                continue
            items.append(item)
            seen_vins.add(vin)
            if len(items) >= limit:
                break

    response = InventorySearchResponse(
        items=items[:limit],
        page=1,
        page_size=limit,
        total=len(items[:limit]),
    )
    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    _HOMEPAGE_SPECIALS_CACHE[cache_key] = (now + _HOMEPAGE_SPECIALS_CACHE_TTL_SECONDS, payload)
    return response


@router.get("/{vin}", response_model=InventoryItem, response_model_exclude_none=True)
def get_inventory_item(
    vin: str,
    db: Session = Depends(get_db),
):
    normalized_vin = (vin or "").strip().upper()
    query = build_inventory_query(engine, {"vin": normalized_vin})
    row = db.execute(query).fetchone()
    if not row:
        manual = (
            db.query(ManualVehicle)
            .filter(ManualVehicle.vin == normalized_vin, ManualVehicle.is_active == True)
            .first()
        )
        if not manual:
            raise HTTPException(status_code=404, detail="VIN not found")
        offer = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
        if not offer:
            key = _normalize_ymm_key(manual.year, manual.make, manual.model)
            offer = _load_offer_ymm_map(db, {key} if key else set()).get(key) if key else None
        offer_out = apply_offer_visibility(offer, (manual.vehicle_type or "new").strip().lower())
        return InventoryItem(
            vin=normalized_vin,
            vehicle_type=(manual.vehicle_type or "new").strip().lower(),
            year=manual.year,
            make=manual.make,
            model=manual.model,
            trim=manual.trim,
            msrp=float(manual.msrp) if manual.msrp is not None else None,
            listed_price=float(manual.listed_price) if manual.listed_price is not None else None,
            mileage=manual.mileage,
            condition=(manual.condition or "").strip().lower() or None,
            details=_serialize_details(manual.details_json),
            photos=_manual_vehicle_photos(manual.photos_json),
            last_seen_at=str(manual.updated_at) if manual.updated_at else None,
            dealer_name=manual.dealer_name,
            dealer_phone=manual.dealer_phone,
            listing_url=manual.listing_url,
            carfax_url=manual.carfax_url,
            offer=OfferOverrideOut(**offer_out) if offer_out else None,
            model_scores=None,
        )

    mapping = row._mapping
    manual_override = (
        db.query(ManualVehicle)
        .filter(ManualVehicle.vin == normalized_vin, ManualVehicle.is_active == True)
        .first()
    )
    row_vehicle_type = (mapping.get("vehicle_type") or "").lower() or None
    effective_vehicle_type = (
        (manual_override.vehicle_type or "").strip().lower()
        if manual_override and manual_override.vehicle_type
        else row_vehicle_type
    )
    effective_year = manual_override.year if manual_override and manual_override.year is not None else mapping.get("year")
    effective_make = manual_override.make if manual_override and manual_override.make else mapping.get("make")
    effective_model = manual_override.model if manual_override and manual_override.model else mapping.get("model")
    effective_trim = manual_override.trim if manual_override and manual_override.trim else mapping.get("trim")
    effective_msrp = manual_override.msrp if manual_override and manual_override.msrp is not None else mapping.get("msrp")
    effective_listed_price = (
        manual_override.listed_price if manual_override and manual_override.listed_price is not None else mapping.get("listed_price")
    )
    effective_mileage = manual_override.mileage if manual_override and manual_override.mileage is not None else mapping.get("mileage")
    effective_condition = (
        (manual_override.condition or "").strip().lower()
        if manual_override and manual_override.condition
        else (str(mapping.get("condition")).lower() if mapping.get("condition") else None)
    )
    effective_details = manual_override.details_json if manual_override and manual_override.details_json else mapping.get("details")
    effective_photos = manual_override.photos_json if manual_override and manual_override.photos_json else mapping.get("photos")
    effective_dealer_name = manual_override.dealer_name if manual_override and manual_override.dealer_name else mapping.get("dealer_name")
    effective_listing_url = manual_override.listing_url if manual_override and manual_override.listing_url else mapping.get("listing_url")
    effective_carfax_url = manual_override.carfax_url if manual_override and manual_override.carfax_url else mapping.get("carfax_url")
    dealer_email = _normalize_email(mapping.get("dealer_email"))
    dealer_phone = manual_override.dealer_phone if manual_override and manual_override.dealer_phone else mapping.get("dealer_phone")
    if not dealer_phone and dealer_email:
        dealer_phone = _dealer_phone_by_email(db, {dealer_email}).get(dealer_email)
    offer = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not offer:
        key = _normalize_ymm_key(effective_year, effective_make, effective_model)
        offer = _load_offer_ymm_map(db, {key} if key else set()).get(key) if key else None
    offer_out = apply_offer_visibility(offer, effective_vehicle_type)

    score = None
    if effective_make and effective_model:
        make_value = effective_make
        model_value = effective_model
        trim_value = effective_trim
        year_value = effective_year
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
        vin=normalized_vin,
        vehicle_type=effective_vehicle_type,
        year=effective_year,
        make=effective_make,
        model=effective_model,
        trim=effective_trim,
        msrp=float(effective_msrp) if effective_msrp is not None else None,
        listed_price=float(effective_listed_price) if effective_listed_price is not None else None,
        mileage=effective_mileage,
        condition=effective_condition,
        details=_serialize_details(effective_details),
        photos=_manual_vehicle_photos(effective_photos) if manual_override and manual_override.photos_json else serialize_photos(effective_photos),
        last_seen_at=str(mapping.get("last_seen_at")) if mapping.get("last_seen_at") else None,
        dealer_name=effective_dealer_name,
        dealer_phone=dealer_phone,
        listing_url=effective_listing_url,
        carfax_url=effective_carfax_url,
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
