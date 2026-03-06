from typing import Any, Dict, List, Optional
import json

from sqlalchemy import MetaData, Table, and_, case, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql import ColumnElement

from app.services.make_normalization import canonical_make_filter_tokens, normalize_text_token

_TABLE_CACHE: Dict[str, Dict[str, Table]] = {}


def load_legacy_tables(engine: Engine) -> Dict[str, Table]:
    cache_key = str(engine.url)
    cached = _TABLE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    metadata = MetaData()
    tables = {
        "dealer_sources": Table("dealer_sources", metadata, autoload_with=engine),
        "scrape_runs": Table("scrape_runs", metadata, autoload_with=engine),
        "canonical_vehicles": Table("canonical_vehicles", metadata, autoload_with=engine),
        "vehicle_listings": Table("vehicle_listings", metadata, autoload_with=engine),
    }
    _TABLE_CACHE[cache_key] = tables
    return tables


def _column_or_none(table: Table, name: str):
    return table.c[name] if name in table.c else None


def _first_available_column(table: Table, candidates: List[str]):
    for name in candidates:
        col = _column_or_none(table, name)
        if col is not None:
            return col
    return None


def _normalized_vehicle_type_expr(table):
    vehicle_type_col = _column_or_none(table, "vehicle_type")
    condition_col = _column_or_none(table, "condition")
    mileage_col = _column_or_none(table, "mileage")

    if vehicle_type_col is None and condition_col is None and mileage_col is None:
        return None

    whens = []
    # Feed-quality override: 0-mile units are effectively new even when source flags used/cpo.
    if mileage_col is not None and condition_col is not None:
        condition_norm = func.lower(condition_col)
        whens.append((and_(mileage_col == 0, condition_norm.in_(["used", "cpo"])), "new"))
    if mileage_col is not None and vehicle_type_col is not None:
        vehicle_type_norm = func.lower(vehicle_type_col)
        whens.append((and_(mileage_col == 0, vehicle_type_norm == "used"), "new"))
    if condition_col is not None:
        condition_norm = func.lower(condition_col)
        whens.append((condition_norm == "new", "new"))
        whens.append((condition_norm.in_(["used", "cpo"]), "used"))
    if vehicle_type_col is not None:
        vehicle_type_norm = func.lower(vehicle_type_col)
        whens.append((vehicle_type_norm.in_(["new", "used"]), vehicle_type_norm))

    return case(*whens, else_=None)


def _best_listing_subquery(listings: Table, filters: Dict[str, Any]) -> ColumnElement:
    status_col = _column_or_none(listings, "status")
    is_active_col = _column_or_none(listings, "is_active")
    vehicle_type_col = _column_or_none(listings, "vehicle_type")
    listed_price_col = _column_or_none(listings, "listed_price")
    msrp_col = _column_or_none(listings, "msrp")
    mileage_col = _column_or_none(listings, "mileage")
    condition_col = _column_or_none(listings, "condition")
    effective_vehicle_type_col = _normalized_vehicle_type_expr(listings)

    query = select(listings)

    vehicle_type_filter = str(filters.get("vehicle_type") or "all").lower()
    if effective_vehicle_type_col is not None and vehicle_type_filter in {"new", "used"}:
        query = query.where(effective_vehicle_type_col == vehicle_type_filter)

    max_price = filters.get("max_price")
    if max_price is not None and effective_vehicle_type_col is not None:
        if vehicle_type_filter == "used" and listed_price_col is not None:
            query = query.where(listed_price_col <= max_price)
        elif vehicle_type_filter == "new" and msrp_col is not None:
            query = query.where(msrp_col <= max_price)
        else:
            price_checks = []
            if listed_price_col is not None:
                price_checks.append(and_(effective_vehicle_type_col == "used", listed_price_col <= max_price))
            if msrp_col is not None:
                price_checks.append(and_(effective_vehicle_type_col == "new", msrp_col <= max_price))
            if price_checks:
                query = query.where(or_(*price_checks))

    max_mileage = filters.get("max_mileage")
    if max_mileage is not None and mileage_col is not None and effective_vehicle_type_col is not None:
        if vehicle_type_filter == "used":
            query = query.where(mileage_col <= max_mileage)
        else:
            query = query.where(or_(effective_vehicle_type_col != "used", mileage_col <= max_mileage))

    condition = str(filters.get("condition") or "all").lower()
    if condition in {"used", "cpo"} and condition_col is not None and effective_vehicle_type_col is not None:
        if vehicle_type_filter == "used":
            query = query.where(func.lower(condition_col) == condition)
        else:
            query = query.where(or_(effective_vehicle_type_col != "used", func.lower(condition_col) == condition))

    filtered = query.subquery()
    status_col = _column_or_none(filtered, "status")
    is_active_col = _column_or_none(filtered, "is_active")
    last_seen = _column_or_none(filtered, "last_seen_at")

    if status_col is not None:
        active_expr = case((status_col == "ACTIVE", 1), (status_col == "active", 1), else_=0)
    elif is_active_col is not None:
        active_expr = case((is_active_col == True, 1), else_=0)
    else:
        active_expr = case((1 == 1, 1), else_=0)

    order_cols = [active_expr.desc()]
    if last_seen is not None:
        order_cols.append(last_seen.desc())

    row_number = func.row_number().over(partition_by=filtered.c.vin, order_by=order_cols).label("rn")
    return select(filtered, row_number).subquery()


def _coalesce(left, right, label: str):
    if left is None and right is None:
        return None
    if left is None:
        return right.label(label)
    if right is None:
        return left.label(label)
    return func.coalesce(left, right).label(label)


def _normalized_text_expr(column):
    expr = func.lower(func.trim(column))
    for token in [" ", "-", ",", ".", "'", '"', "_", "/", "\u2022"]:
        expr = func.replace(expr, token, "")
    return expr


def build_inventory_query(engine: Engine, filters: Dict[str, Any]):
    tables = load_legacy_tables(engine)
    listings = tables["vehicle_listings"]
    canonical = tables["canonical_vehicles"]
    dealer_sources = tables["dealer_sources"]

    best_listing = _best_listing_subquery(listings, filters)

    vin_col = best_listing.c.vin
    vehicle_type_col = _normalized_vehicle_type_expr(best_listing)
    if vehicle_type_col is not None:
        vehicle_type_col = vehicle_type_col.label("vehicle_type")
    year_col = _coalesce(_column_or_none(canonical, "year"), _column_or_none(best_listing, "year"), "year")
    make_col = _coalesce(_column_or_none(canonical, "make"), _column_or_none(best_listing, "make"), "make")
    model_col = _coalesce(_column_or_none(canonical, "model"), _column_or_none(best_listing, "model"), "model")
    trim_col = _coalesce(_column_or_none(canonical, "trim"), _column_or_none(best_listing, "trim"), "trim")
    msrp_col = _coalesce(_column_or_none(canonical, "msrp"), _column_or_none(best_listing, "msrp"), "msrp")
    listed_price_col = _column_or_none(best_listing, "listed_price")
    mileage_col = _column_or_none(best_listing, "mileage")
    condition_col = _column_or_none(best_listing, "condition")
    details_col = _coalesce(
        _column_or_none(canonical, "details"),
        _column_or_none(best_listing, "listing_payload"),
        "details",
    )
    photos_col = _column_or_none(best_listing, "photo_urls")
    if photos_col is not None:
        photos_col = photos_col.label("photos")
    last_seen_col = _column_or_none(best_listing, "last_seen_at")
    source_id_col = _column_or_none(best_listing, "source_id")
    listing_url_col = _column_or_none(best_listing, "url")
    if listing_url_col is not None:
        listing_url_col = listing_url_col.label("listing_url")
    carfax_col = _column_or_none(best_listing, "carfax_url")

    dealer_name_col = None
    if "dealer_name" in dealer_sources.c:
        dealer_name_col = dealer_sources.c.dealer_name.label("dealer_name")
    dealer_phone_col = _first_available_column(
        dealer_sources,
        ["phone", "phone_number", "dealer_phone", "contact_phone", "sales_phone"],
    )
    if dealer_phone_col is not None:
        dealer_phone_col = dealer_phone_col.label("dealer_phone")
    dealer_email_col = _first_available_column(
        dealer_sources,
        ["email", "contact_email", "dealer_email"],
    )
    if dealer_email_col is not None:
        dealer_email_col = dealer_email_col.label("dealer_email")

    sort_price_col = None
    if vehicle_type_col is not None:
        sort_price_col = case(
            (func.lower(vehicle_type_col) == "used", listed_price_col),
            else_=msrp_col,
        ).label("sort_price")

    columns = [vin_col]
    for col in [
        vehicle_type_col,
        year_col,
        make_col,
        model_col,
        trim_col,
        msrp_col,
        listed_price_col,
        mileage_col,
        condition_col,
        details_col,
        photos_col,
        last_seen_col,
        source_id_col,
        listing_url_col,
        carfax_col,
        dealer_name_col,
        dealer_phone_col,
        dealer_email_col,
        sort_price_col,
    ]:
        if col is not None:
            columns.append(col)

    from_clause = best_listing.outerjoin(canonical, canonical.c.vin == best_listing.c.vin)
    if "id" in dealer_sources.c and source_id_col is not None:
        from_clause = from_clause.outerjoin(
            dealer_sources, dealer_sources.c.id == best_listing.c.source_id
        )
    base = select(*columns).select_from(from_clause).where(
        best_listing.c.rn == 1, vin_col.is_not(None)
    )

    if "make" in filters and filters["make"] and make_col is not None:
        make_tokens = canonical_make_filter_tokens(str(filters["make"]))
        if make_tokens:
            base = base.where(_normalized_text_expr(make_col).in_(sorted(make_tokens)))
        else:
            base = base.where(_normalized_text_expr(make_col) == normalize_text_token(str(filters["make"])))
    if "model" in filters and filters["model"] and model_col is not None:
        base = base.where(_normalized_text_expr(model_col) == normalize_text_token(str(filters["model"])))
    if "trim" in filters and filters["trim"] and trim_col is not None:
        base = base.where(_normalized_text_expr(trim_col) == normalize_text_token(str(filters["trim"])))
    if "year" in filters and filters["year"] and year_col is not None:
        base = base.where(year_col == filters["year"])
    if "vin" in filters and filters["vin"]:
        base = base.where(vin_col == filters["vin"])

    return base


def build_inventory_count_query(engine: Engine, filters: Dict[str, Any]):
    """Lighter count for inventory: uses only the best-listing subquery (no canonical/dealer joins)."""
    tables = load_legacy_tables(engine)
    listings = tables["vehicle_listings"]
    best_listing = _best_listing_subquery(listings, filters)
    return (
        select(func.count())
        .select_from(best_listing)
        .where(best_listing.c.rn == 1, best_listing.c.vin.is_not(None))
    )


def serialize_photos(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw[:5]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data[:5]
        except json.JSONDecodeError:
            return [raw]
    return []

