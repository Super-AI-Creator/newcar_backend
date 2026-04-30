from typing import Any, Optional
from datetime import datetime, timezone
from pathlib import Path
import re
import json
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.core.deps import get_db, require_role
from app.core.security import hash_password
from app.models.auth_otp import AuthOtp
from app.models.broker_message import BrokerMessage
from app.models.credit_application import CreditApplication
from app.models.deal import Deal
from app.models.deal_event import DealEvent
from app.models.document_submission import DocumentSubmission
from app.models.enums import OfferSource, UserRole
from app.models.favorite import Favorite
from app.models.homepage_featured_vehicle import HomepageFeaturedVehicle
from app.models.lead_request import LeadRequest
from app.models.manual_vehicle import ManualVehicle
from app.models.offer_override import OfferOverride
from app.models.model_score import ModelScore
from app.models.seo_page_setting import SeoPageSetting
from app.landing_footer_defaults import FOOTER_DISCLOSURE_DEFAULT
from app.landing_slide_urls import normalize_hero_slide_urls_in_payload
from app.models.landing_page_content import LandingPageContent
from app.models.sheet_sources_meta import SheetSourceMeta
from app.models.testimonial import Testimonial
from app.models.article import Article
from app.models.user import User
from app.schemas.user import UserOut
from app.services.cloudinary import CloudinaryUploadError, cloudinary_is_configured, upload_image_to_cloudinary
from app.services.offers import set_offer_visibility
from app.services.lead_delivery import build_lead_webhook_payload, is_lead_webhook_enabled, send_lead_webhook
from app.services.legacy_tables import build_inventory_query, load_legacy_tables
from app.services.sheets_runner import run_sheets_sync_with_lock
from app.routes.inventory import get_inventory_item
from app.routes.landing import _default_hero_falling, invalidate_landing_page_cache

router = APIRouter(prefix="/admin", tags=["admin"])
MAX_HOMEPAGE_FEATURED_VEHICLES = 6
_MONTH_KEY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SEO_PAGE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_MANUAL_PHOTO_BYTES = 8 * 1024 * 1024
DEFAULT_HOMEPAGE_FEATURED_KEY = "default"
_MANUAL_PHOTO_MIME_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_MANUAL_PHOTO_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "manual-vehicles"


@router.get("/sources")
def sources(db: Session = Depends(get_db), user=Depends(require_role("broker_admin"))):
    tables = load_legacy_tables(engine)
    dealer_sources = tables["dealer_sources"]
    query = select(dealer_sources)

    rows = db.execute(query).fetchall()
    results = []
    for row in rows:
        mapping = row._mapping
        results.append({k: v for k, v in mapping.items()})

    return {"items": results}


@router.post("/sync-sheets")
def sync_sheets(db: Session = Depends(get_db), user=Depends(require_role("broker_admin", "super_admin"))):
    return _sync_sheets(db)


@router.post("/sync")
def sync_sheets_alias(db: Session = Depends(get_db), user=Depends(require_role("broker_admin", "super_admin"))):
    return _sync_sheets(db)


@router.get("/sync-status")
def sync_status(db: Session = Depends(get_db), user=Depends(require_role("broker_admin", "super_admin"))):
    rows = (
        db.query(SheetSourceMeta)
        .filter(SheetSourceMeta.sheet_name.in_(["offers", "scores"]))
        .order_by(SheetSourceMeta.last_synced_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "sheet_name": row.sheet_name,
                "sheet_id": row.sheet_id,
                "tab_name": row.tab_name,
                "last_synced_at": str(row.last_synced_at) if row.last_synced_at else None,
                "last_row_hash": row.last_row_hash,
                "last_error": row.last_error,
            }
            for row in rows
        ],
        "counts": {
            "offer_overrides": db.query(func.count(OfferOverride.id)).scalar() or 0,
            "model_scores": db.query(func.count(ModelScore.id)).scalar() or 0,
        },
    }


@router.get("/lead-delivery")
def lead_delivery_logs(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "super_admin")),
):
    query = db.query(LeadRequest)
    if status in {"pending", "sent", "failed", "skipped"}:
        query = query.filter(LeadRequest.webhook_status == status)
    if q:
        needle = q.strip()
        if needle:
            query = query.filter(
                (LeadRequest.email.ilike(f"%{needle}%"))
                | (LeadRequest.phone.ilike(f"%{needle}%"))
                | (LeadRequest.vin.ilike(f"%{needle}%"))
                | (LeadRequest.name.ilike(f"%{needle}%"))
            )

    rows = query.order_by(LeadRequest.created_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "lead_id": int(row.id),
                "created_at": str(row.created_at) if row.created_at else None,
                "name": row.name,
                "email": row.email,
                "phone": row.phone,
                "vin": row.vin,
                "vehicle": row.vehicle,
                "source": row.source,
                "notes": row.notes,
                "webhook_status": row.webhook_status,
                "webhook_attempts": int(row.webhook_attempts or 0),
                "webhook_last_error": row.webhook_last_error,
                "webhook_last_attempt_at": str(row.webhook_last_attempt_at) if row.webhook_last_attempt_at else None,
                "webhook_delivered_at": str(row.webhook_delivered_at) if row.webhook_delivered_at else None,
            }
            for row in rows
        ]
    }


@router.post("/lead-delivery/{lead_id}/retry")
def retry_lead_delivery(
    lead_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin", "super_admin")),
):
    if not is_lead_webhook_enabled():
        raise HTTPException(status_code=400, detail="Lead webhook is not configured.")

    row = db.query(LeadRequest).filter(LeadRequest.id == lead_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    row.webhook_status = "pending"
    row.webhook_last_error = None
    db.commit()
    db.refresh(row)

    background_tasks.add_task(send_lead_webhook, build_lead_webhook_payload(row))
    return {"queued": True, "lead_id": int(row.id), "webhook_status": row.webhook_status}


def _sync_sheets(db: Session):
    if not (db and engine):
        raise HTTPException(status_code=500, detail="Database not ready")
    return run_sheets_sync_with_lock(
        db,
        wait_seconds=max(0, int(settings.sheets_webhook_lock_wait_seconds or 0)),
    )


class OfferOverrideUpdate(BaseModel):
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    discounted_price: Optional[float] = None
    term_months: Optional[int] = None
    miles_per_year: Optional[int] = None


class OfferOverrideYmmUpdate(OfferOverrideUpdate):
    year: int
    make: str
    model: str
    vehicle_type: Optional[str] = None


def _normalize_vin(vin: str) -> str:
    normalized = (vin or "").strip().upper()
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="VIN must be at least 8 characters.")
    return normalized


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


def _normalize_seo_page_key(page_key: str) -> str:
    normalized = (page_key or "").strip().lower()
    if not _SEO_PAGE_KEY_RE.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="page_key must be lowercase letters/numbers and may include _ or - (max 64 chars).",
        )
    return normalized


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_json_ld(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _table_col(table, *candidates: str):
    for name in candidates:
        if name in table.c:
            return table.c[name]
    return None


def _truthy_filter(column):
    if column is None:
        return true()
    predicates = [column == 1, column == True]  # noqa: E712
    type_name = str(getattr(column, "type", "")).lower()
    if any(token in type_name for token in ["char", "text", "string", "enum"]):
        predicates.append(func.lower(func.trim(column)).in_(["1", "true", "yes", "active", "enabled"]))
    return or_(*predicates)


def _active_listing_filter(listings_table):
    status_col = _table_col(listings_table, "status")
    is_active_col = _table_col(listings_table, "is_active")
    predicates = []
    if status_col is not None:
        predicates.append(func.lower(func.trim(status_col)) == "active")
    if is_active_col is not None:
        predicates.append(_truthy_filter(is_active_col))
    if not predicates:
        return true()
    return or_(*predicates)


def _normalized_listing_vehicle_type_expr(listings_table):
    vehicle_type_col = _table_col(listings_table, "vehicle_type")
    condition_col = _table_col(listings_table, "condition")
    whens = []
    if condition_col is not None:
        condition_norm = func.lower(func.trim(condition_col))
        whens.append((condition_norm == "new", "new"))
        whens.append((condition_norm.in_(["used", "cpo"]), "used"))
    if vehicle_type_col is not None:
        vehicle_type_norm = func.lower(func.trim(vehicle_type_col))
        whens.append((vehicle_type_norm == "new", "new"))
        whens.append((vehicle_type_norm == "used", "used"))
    if not whens:
        return None
    return case(*whens, else_=None)


def _serialize_seo_page_setting(row: SeoPageSetting) -> dict:
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
        "is_active": bool(row.is_active),
        "updated_at": str(row.updated_at) if row.updated_at else None,
        "created_at": str(row.created_at) if row.created_at else None,
    }


@router.get("/general-status")
def general_status(
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    tables = load_legacy_tables(engine)
    dealer_sources = tables["dealer_sources"]
    listings = tables["vehicle_listings"]

    enabled_col = _table_col(dealer_sources, "enabled", "is_active", "active")
    source_status_col = _table_col(dealer_sources, "status", "source_status", "last_scrape_status")
    active_source_filter = _truthy_filter(enabled_col)
    if source_status_col is not None:
        active_source_filter = or_(active_source_filter, func.lower(func.trim(source_status_col)) == "active")

    dealer_name_col = _table_col(dealer_sources, "dealer_name", "name", "brand", "website_url")
    active_dealer_names: list[str] = []
    active_source_ids: list[int] = []

    if "id" in dealer_sources.c:
        active_source_ids = [
            int(row[0])
            for row in db.execute(
                select(dealer_sources.c.id).where(active_source_filter)
            ).fetchall()
            if row and row[0] is not None
        ]

    if dealer_name_col is not None:
        name_rows = db.execute(
            select(dealer_name_col)
            .where(active_source_filter, dealer_name_col.is_not(None), func.trim(dealer_name_col) != "")
            .distinct()
            .order_by(dealer_name_col.asc())
        ).fetchall()
        active_dealer_names = [str(row[0]).strip() for row in name_rows if row and row[0]]

    listing_filters = [_active_listing_filter(listings)]
    if "vin" in listings.c:
        listing_filters.append(listings.c.vin.is_not(None))
    if active_source_ids and "source_id" in listings.c:
        listing_filters.append(listings.c.source_id.in_(active_source_ids))

    normalized_type_expr = _normalized_listing_vehicle_type_expr(listings)
    vehicle_counts = {"new": 0, "used": 0}

    if normalized_type_expr is not None and "vin" in listings.c:
        order_columns = []
        if "last_seen_at" in listings.c:
            order_columns.append(listings.c.last_seen_at.desc())
        elif "updated_at" in listings.c:
            order_columns.append(listings.c.updated_at.desc())
        elif "id" in listings.c:
            order_columns.append(listings.c.id.desc())

        if not order_columns:
            order_columns.append(listings.c.vin.asc())

        ranked = select(
            listings.c.vin.label("vin"),
            normalized_type_expr.label("vehicle_type"),
            func.row_number()
            .over(partition_by=listings.c.vin, order_by=order_columns)
            .label("rn"),
        ).where(*listing_filters)

        ranked_subquery = ranked.subquery()
        rows = db.execute(
            select(ranked_subquery.c.vehicle_type, func.count())
            .where(
                ranked_subquery.c.rn == 1,
                ranked_subquery.c.vehicle_type.is_not(None),
            )
            .group_by(ranked_subquery.c.vehicle_type)
        ).fetchall()
        for vehicle_type, count in rows:
            normalized = str(vehicle_type or "").strip().lower()
            if normalized in vehicle_counts:
                vehicle_counts[normalized] = int(count or 0)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dealers": {
            "active_count": len(active_dealer_names),
            "names": active_dealer_names,
        },
        "vehicles": {
            "active_new_count": int(vehicle_counts["new"]),
            "active_used_count": int(vehicle_counts["used"]),
            "active_total_count": int(vehicle_counts["new"] + vehicle_counts["used"]),
        },
    }


def _vin_exists_in_inventory(db: Session, vin: str) -> bool:
    if db.execute(build_inventory_query(engine, {"vin": vin}).limit(1)).first() is not None:
        return True
    manual = (
        db.query(ManualVehicle)
        .filter(ManualVehicle.vin == vin, ManualVehicle.is_active == True)
        .first()
    )
    return manual is not None


def _vehicle_summary_by_vin(db: Session, vin: str) -> dict:
    row = db.execute(build_inventory_query(engine, {"vin": vin}).limit(1)).first()
    offer = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
    if row:
        mapping = row._mapping
        return {
            "vin": vin,
            "found": True,
            "year": mapping.get("year"),
            "make": mapping.get("make"),
            "model": mapping.get("model"),
            "trim": mapping.get("trim"),
            "monthly_payment": float(offer.monthly_payment) if offer and offer.monthly_payment is not None else None,
            "down_payment": float(offer.down_payment) if offer and offer.down_payment is not None else None,
            "discounted_price": float(offer.discounted_price) if offer and offer.discounted_price is not None else None,
        }
    manual = (
        db.query(ManualVehicle)
        .filter(ManualVehicle.vin == vin, ManualVehicle.is_active == True)
        .first()
    )
    if manual:
        return {
            "vin": vin,
            "found": True,
            "year": manual.year,
            "make": manual.make,
            "model": manual.model,
            "trim": manual.trim,
            "monthly_payment": float(offer.monthly_payment) if offer and offer.monthly_payment is not None else None,
            "down_payment": float(offer.down_payment) if offer and offer.down_payment is not None else None,
            "discounted_price": float(offer.discounted_price) if offer and offer.discounted_price is not None else None,
        }
    return {"vin": vin, "found": False}


def _serialize_homepage_featured(db: Session, month_key: str):
    rows = (
        db.query(HomepageFeaturedVehicle)
        .filter(HomepageFeaturedVehicle.month_key == month_key)
        .order_by(HomepageFeaturedVehicle.position.asc(), HomepageFeaturedVehicle.id.asc())
        .all()
    )
    vins = [str(row.vin).strip().upper() for row in rows if row.vin]
    items = []
    for row in rows:
        vin = str(row.vin).strip().upper()
        items.append(
            {
                "position": int(row.position),
                "vin": vin,
                "updated_at": str(row.updated_at) if row.updated_at else None,
                "vehicle": _vehicle_summary_by_vin(db, vin),
            }
        )
    return {
        "month": month_key,
        "max_items": MAX_HOMEPAGE_FEATURED_VEHICLES,
        "count": len(items),
        "vins": vins,
        "items": items,
    }


class HomepageFeaturedUpdate(BaseModel):
    vins: list[str] = []


class ManualVehicleUpsert(BaseModel):
    vehicle_type: Optional[str] = "new"
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    msrp: Optional[float] = None
    listed_price: Optional[float] = None
    mileage: Optional[int] = None
    condition: Optional[str] = None
    photos: list[str] = []
    details: Optional[dict] = None
    dealer_name: Optional[str] = None
    dealer_phone: Optional[str] = None
    listing_url: Optional[str] = None
    carfax_url: Optional[str] = None
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    discounted_price: Optional[float] = None
    term_months: Optional[int] = None
    miles_per_year: Optional[int] = None


class SeoPageSettingUpsert(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[str] = None
    canonical_url: Optional[str] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image_url: Optional[str] = None
    robots: Optional[str] = None
    json_ld: Optional[Any] = None
    is_active: Optional[bool] = True


def _serialize_manual_vehicle(row: ManualVehicle, offer: Optional[OfferOverride] = None) -> dict:
    photos = []
    details = None
    if row.photos_json:
        try:
            parsed = json.loads(row.photos_json)
            if isinstance(parsed, list):
                photos = [str(item) for item in parsed if item]
        except Exception:
            photos = []
    if row.details_json:
        try:
            parsed = json.loads(row.details_json)
            if isinstance(parsed, dict):
                details = parsed
        except Exception:
            details = None
    return {
        "vin": row.vin,
        "vehicle_type": row.vehicle_type,
        "year": row.year,
        "make": row.make,
        "model": row.model,
        "trim": row.trim,
        "msrp": row.msrp,
        "listed_price": row.listed_price,
        "mileage": row.mileage,
        "condition": row.condition,
        "photos": photos,
        "details": details,
        "dealer_name": row.dealer_name,
        "dealer_phone": row.dealer_phone,
        "listing_url": row.listing_url,
        "carfax_url": row.carfax_url,
        "is_active": bool(row.is_active),
        "updated_at": str(row.updated_at) if row.updated_at else None,
        "down_payment": float(offer.down_payment) if offer and offer.down_payment is not None else None,
        "monthly_payment": float(offer.monthly_payment) if offer and offer.monthly_payment is not None else None,
        "discounted_price": float(offer.discounted_price) if offer and offer.discounted_price is not None else None,
        "term_months": int(offer.term_months) if offer and offer.term_months is not None else None,
        "miles_per_year": int(offer.miles_per_year) if offer and offer.miles_per_year is not None else None,
    }


@router.get("/homepage-featured")
def get_homepage_featured(
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    return _serialize_homepage_featured(db, _homepage_featured_key_for_read(db))


@router.put("/homepage-featured")
def set_homepage_featured(
    payload: HomepageFeaturedUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    month_key = DEFAULT_HOMEPAGE_FEATURED_KEY
    ordered_vins: list[str] = []
    seen: set[str] = set()
    for vin in payload.vins:
        normalized = _normalize_vin(vin)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered_vins.append(normalized)

    if len(ordered_vins) > MAX_HOMEPAGE_FEATURED_VEHICLES:
        raise HTTPException(
            status_code=400,
            detail=f"You can feature up to {MAX_HOMEPAGE_FEATURED_VEHICLES} vehicles.",
        )

    missing = [vin for vin in ordered_vins if not _vin_exists_in_inventory(db, vin)]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Some VINs were not found in inventory: {', '.join(missing)}",
        )

    (
        db.query(HomepageFeaturedVehicle)
        .filter(HomepageFeaturedVehicle.month_key == month_key)
        .delete(synchronize_session=False)
    )
    for idx, vin in enumerate(ordered_vins, start=1):
        # Precompute full landing-card payload so public homepage visits are fast.
        item = get_inventory_item(vin=vin, db=db)
        card_payload = item.model_dump() if hasattr(item, "model_dump") else item.dict()
        db.add(
            HomepageFeaturedVehicle(
                month_key=month_key,
                position=idx,
                vin=vin,
                card_payload_json=json.dumps(card_payload),
                updated_by_user_id=getattr(user, "id", None),
            )
        )

    db.commit()
    try:
        from app.routes.inventory import _HOMEPAGE_SPECIALS_CACHE
        _HOMEPAGE_SPECIALS_CACHE.clear()
    except Exception:
        pass
    return _serialize_homepage_featured(db, month_key)


@router.get("/manual-vehicles")
def list_manual_vehicles(
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    query = db.query(ManualVehicle)
    if not include_inactive:
        query = query.filter(ManualVehicle.is_active == True)
    if q:
        needle = q.strip()
        if needle:
            query = query.filter(
                (ManualVehicle.vin.ilike(f"%{needle}%"))
                | (ManualVehicle.make.ilike(f"%{needle}%"))
                | (ManualVehicle.model.ilike(f"%{needle}%"))
                | (ManualVehicle.trim.ilike(f"%{needle}%"))
            )

    rows = query.order_by(ManualVehicle.updated_at.desc(), ManualVehicle.created_at.desc()).limit(limit).all()
    vins = [row.vin for row in rows if row.vin]
    offers = db.query(OfferOverride).filter(OfferOverride.vin.in_(vins)).all() if vins else []
    offer_map = {row.vin: row for row in offers}
    return {"items": [_serialize_manual_vehicle(row, offer_map.get(row.vin)) for row in rows]}


@router.put("/manual-vehicles/{vin}")
def upsert_manual_vehicle(
    vin: str,
    payload: ManualVehicleUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    normalized_vin = _normalize_vin(vin)
    vehicle_type = (payload.vehicle_type or "new").strip().lower()
    if vehicle_type not in {"new", "used"}:
        raise HTTPException(status_code=400, detail="vehicle_type must be 'new' or 'used'.")

    row = db.query(ManualVehicle).filter(ManualVehicle.vin == normalized_vin).first()
    if not row:
        row = ManualVehicle(vin=normalized_vin)
        db.add(row)

    row.vehicle_type = vehicle_type
    row.year = payload.year
    row.make = payload.make.strip() if payload.make else None
    row.model = payload.model.strip() if payload.model else None
    row.trim = payload.trim.strip() if payload.trim else None
    row.msrp = payload.msrp
    row.listed_price = payload.listed_price
    row.mileage = payload.mileage
    row.condition = payload.condition.strip().lower() if payload.condition else None
    row.photos_json = json.dumps([str(item).strip() for item in payload.photos if str(item).strip()])
    row.details_json = json.dumps(payload.details or {}) if payload.details is not None else None
    row.dealer_name = payload.dealer_name.strip() if payload.dealer_name else None
    row.dealer_phone = payload.dealer_phone.strip() if payload.dealer_phone else None
    row.listing_url = payload.listing_url.strip() if payload.listing_url else None
    row.carfax_url = payload.carfax_url.strip() if payload.carfax_url else None
    row.is_active = True
    row.updated_by_user_id = getattr(user, "id", None)

    offer_payload_has_values = any(
        value is not None
        for value in [
            payload.down_payment,
            payload.monthly_payment,
            payload.discounted_price,
            payload.term_months,
            payload.miles_per_year,
        ]
    )
    if offer_payload_has_values:
        offer = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
        if not offer:
            offer = OfferOverride(vin=normalized_vin, source=OfferSource.broker, updated_by_user_id=getattr(user, "id", None))
            db.add(offer)
        offer.down_payment = payload.down_payment
        offer.monthly_payment = payload.monthly_payment
        offer.discounted_price = payload.discounted_price
        offer.term_months = payload.term_months
        offer.miles_per_year = payload.miles_per_year
        offer.source = OfferSource.broker
        offer.updated_by_user_id = getattr(user, "id", None)
        set_offer_visibility(offer)

    db.commit()
    db.refresh(row)
    offer = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    return {"status": "updated", "item": _serialize_manual_vehicle(row, offer)}


@router.post("/manual-vehicles/upload-photo")
async def upload_manual_vehicle_photo(
    file: UploadFile = File(...),
    user=Depends(require_role("super_admin")),
):
    _ = user
    content_type = (file.content_type or "application/octet-stream").lower()
    suffix = _MANUAL_PHOTO_MIME_SUFFIX.get(content_type)
    if not suffix:
        raise HTTPException(status_code=415, detail="Unsupported image type. Use JPG, PNG, or WEBP.")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Image file is required.")
    if len(payload) > MAX_MANUAL_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 8MB or smaller.")

    source_filename = (file.filename or "").strip() or f"manual_vehicle{suffix}"

    if cloudinary_is_configured():
        try:
            uploaded_url = await upload_image_to_cloudinary(
                payload,
                filename=source_filename,
                content_type=content_type,
                folder=(settings.cloudinary_upload_folder or "manual-vehicles"),
            )
        except CloudinaryUploadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "url": uploaded_url,
            "filename": source_filename,
            "content_type": content_type,
            "size_bytes": len(payload),
            "provider": "cloudinary",
        }

    _MANUAL_PHOTO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}{suffix}"
    path = _MANUAL_PHOTO_UPLOAD_DIR / filename
    path.write_bytes(payload)

    return {
        "url": f"/uploads/manual-vehicles/{filename}",
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(payload),
        "provider": "local",
    }


@router.delete("/manual-vehicles/{vin}")
def delete_manual_vehicle(
    vin: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    normalized_vin = _normalize_vin(vin)
    row = db.query(ManualVehicle).filter(ManualVehicle.vin == normalized_vin).first()
    if not row:
        raise HTTPException(status_code=404, detail="Manual vehicle not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "vin": normalized_vin}


@router.get("/seo-settings")
def list_seo_settings(
    q: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    query = db.query(SeoPageSetting)
    if not include_inactive:
        query = query.filter(SeoPageSetting.is_active == True)
    if q:
        needle = q.strip()
        if needle:
            query = query.filter(
                (SeoPageSetting.page_key.ilike(f"%{needle}%"))
                | (SeoPageSetting.title.ilike(f"%{needle}%"))
                | (SeoPageSetting.description.ilike(f"%{needle}%"))
            )
    rows = query.order_by(SeoPageSetting.page_key.asc()).limit(limit).all()
    return {"items": [_serialize_seo_page_setting(row) for row in rows]}


@router.get("/seo-settings/{page_key}")
def get_seo_setting(
    page_key: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    normalized_key = _normalize_seo_page_key(page_key)
    row = db.query(SeoPageSetting).filter(SeoPageSetting.page_key == normalized_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="SEO setting not found.")
    return _serialize_seo_page_setting(row)


@router.put("/seo-settings/{page_key}")
def upsert_seo_setting(
    page_key: str,
    payload: SeoPageSettingUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    normalized_key = _normalize_seo_page_key(page_key)
    row = db.query(SeoPageSetting).filter(SeoPageSetting.page_key == normalized_key).first()
    if not row:
        row = SeoPageSetting(page_key=normalized_key)
        db.add(row)

    row.title = _clean_optional_text(payload.title)
    row.description = _clean_optional_text(payload.description)
    row.keywords = _clean_optional_text(payload.keywords)
    row.canonical_url = _clean_optional_text(payload.canonical_url)
    row.og_title = _clean_optional_text(payload.og_title)
    row.og_description = _clean_optional_text(payload.og_description)
    row.og_image_url = _clean_optional_text(payload.og_image_url)
    row.robots = _clean_optional_text(payload.robots)
    row.json_ld_text = json.dumps(payload.json_ld) if payload.json_ld is not None else None
    if payload.is_active is not None:
        row.is_active = bool(payload.is_active)
    row.updated_by_user_id = getattr(user, "id", None)

    db.commit()
    db.refresh(row)
    return {"status": "updated", "item": _serialize_seo_page_setting(row)}


@router.delete("/seo-settings/{page_key}")
def delete_seo_setting(
    page_key: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    normalized_key = _normalize_seo_page_key(page_key)
    row = db.query(SeoPageSetting).filter(SeoPageSetting.page_key == normalized_key).first()
    if not row:
        raise HTTPException(status_code=404, detail="SEO setting not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "page_key": normalized_key}


# ---------- Landing page content (super_admin) ----------
class LandingFallingPhrasesPayload(BaseModel):
    enabled: Optional[bool] = None
    phrases: Optional[list[str]] = None
    duration_min: Optional[int] = None
    duration_max: Optional[int] = None
    max_phrases: Optional[int] = None
    stagger: Optional[float] = None


class LandingHeroPayload(BaseModel):
    kicker: Optional[str] = None
    headline: Optional[str] = None
    subtext: Optional[str] = None
    slide_urls: Optional[list[str]] = None
    slide_focus: Optional[list[str]] = None
    falling: Optional[LandingFallingPhrasesPayload] = None


class LandingLeasePayload(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None


class LandingHowItWorksStep(BaseModel):
    image_url: Optional[str] = None
    label: Optional[str] = None
    image_focus: Optional[str] = None


class LandingFooterPayload(BaseModel):
    facebook_url: Optional[str] = None
    twitter_url: Optional[str] = None
    google_plus_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    address_line: Optional[str] = None
    phone_line: Optional[str] = None
    footer_disclosure: Optional[str] = None
    copyright_line: Optional[str] = None
    link_lease_label: Optional[str] = None
    link_lease_url: Optional[str] = None
    link_broker_label: Optional[str] = None
    link_broker_url: Optional[str] = None


class LandingPagePayload(BaseModel):
    hero: Optional[LandingHeroPayload] = None
    lease: Optional[LandingLeasePayload] = None
    how_it_works: Optional[list[LandingHowItWorksStep]] = None
    footer: Optional[LandingFooterPayload] = None


def _landing_default() -> dict:
    return {
        "hero": {
            "kicker": "SHOP,  GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW",
            "headline": "Buy Any New Car in California Without the Dealership",
            "subtext": "SHOP, GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW.",
            "slide_urls": [
                "/images/landing-1.jpg",
                "/images/landing-2.jpg",
                "/images/landing-3.jpg",
                "/images/landing-4.jpg",
            ],
            "slide_focus": ["center", "center", "center", "center"],
            "falling": _default_hero_falling(),
        },
        "lease": {
            "title": "Current Lease Specials Los Angeles",
            "subtitle": "Shop and compare hundreds of lease offers, if they make it, we have it! 818-705-9200",
        },
        "how_it_works": [
            {"image_url": "/images/hero-cars.jpg", "label": "Browse Statewide Inventory", "image_focus": "center"},
            {"image_url": "/images/deal-1.jpg", "label": "Get Your Best Rate", "image_focus": "center"},
            {"image_url": "/images/panel-cars.jpg", "label": "Home Delivery With a Bow", "image_focus": "center"},
        ],
        "footer": {
            "facebook_url": "https://www.facebook.com/newcarsuperstore/",
            "twitter_url": "https://twitter.com/autobrokerla",
            "google_plus_url": "https://plus.google.com/101810114903929491113",
            "instagram_url": "https://www.instagram.com/newcarsuperstore/",
            "youtube_url": "https://www.youtube.com/channel/UCfnPH7n_x1cHc5WXDb0zMJQ",
            "address_line": "2671 Ventura Blvd Suite Oxnard CA 93036",
            "phone_line": "818.705.9200, 818.705.9202",
            "footer_disclosure": FOOTER_DISCLOSURE_DEFAULT,
            "copyright_line": "",
            "link_lease_label": "Lease Specials Los Angeles",
            "link_lease_url": "/lease-specials",
            "link_broker_label": "Auto Broker Los Angeles",
            "link_broker_url": "/most-reviewed-auto-broker-los-angeles",
        },
    }


@router.get("/landing-page")
def admin_get_landing_page(db: Session = Depends(get_db), user=Depends(require_role("super_admin"))):
    _ = user
    row = db.query(LandingPageContent).filter(LandingPageContent.id == 1).first()
    if not row or not row.content or not row.content.strip():
        return normalize_hero_slide_urls_in_payload(_landing_default())
    try:
        data = json.loads(row.content)
        payload = data if isinstance(data, dict) else _landing_default()
    except Exception:
        payload = _landing_default()
    foot = payload.get("footer")
    if isinstance(foot, dict) and not (str(foot.get("footer_disclosure") or "").strip()):
        payload = {
            **payload,
            "footer": {**foot, "footer_disclosure": FOOTER_DISCLOSURE_DEFAULT},
        }
    hero = payload.get("hero")
    if isinstance(hero, dict) and not isinstance(hero.get("falling"), dict):
        payload = {**payload, "hero": {**hero, "falling": _default_hero_falling()}}
    return normalize_hero_slide_urls_in_payload(payload)


@router.put("/landing-page")
def admin_upsert_landing_page(
    payload: LandingPagePayload,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    row = db.query(LandingPageContent).filter(LandingPageContent.id == 1).first()
    if not row:
        row = LandingPageContent(id=1)
        db.add(row)
    current = _landing_default()
    if row.content and row.content.strip():
        try:
            current = json.loads(row.content)
            if not isinstance(current, dict):
                current = _landing_default()
        except Exception:
            pass
    if payload.hero is not None:
        if payload.hero.kicker is not None:
            current.setdefault("hero", {})["kicker"] = payload.hero.kicker
        if payload.hero.headline is not None:
            current.setdefault("hero", {})["headline"] = payload.hero.headline
        if payload.hero.subtext is not None:
            current.setdefault("hero", {})["subtext"] = payload.hero.subtext
        if payload.hero.slide_urls is not None:
            current.setdefault("hero", {})["slide_urls"] = payload.hero.slide_urls
        if payload.hero.slide_focus is not None:
            current.setdefault("hero", {})["slide_focus"] = payload.hero.slide_focus
        if payload.hero.falling is not None:
            hf = payload.hero.falling
            hero = current.setdefault("hero", {})
            prev = hero.get("falling") if isinstance(hero.get("falling"), dict) else _default_hero_falling()
            nf = {**prev}
            if hf.enabled is not None:
                nf["enabled"] = bool(hf.enabled)
            if hf.phrases is not None:
                nf["phrases"] = [str(p).strip() for p in hf.phrases if str(p).strip()]
            if hf.duration_min is not None:
                nf["duration_min"] = max(8, min(90, int(hf.duration_min)))
            if hf.duration_max is not None:
                nf["duration_max"] = max(8, min(120, int(hf.duration_max)))
            if nf.get("duration_min", 0) > nf.get("duration_max", 0):
                nf["duration_min"], nf["duration_max"] = nf["duration_max"], nf["duration_min"]
            if hf.max_phrases is not None:
                nf["max_phrases"] = max(1, min(24, int(hf.max_phrases)))
            if hf.stagger is not None:
                nf["stagger"] = max(0.8, min(5.0, float(hf.stagger)))
            hero["falling"] = nf
    if payload.lease is not None:
        if payload.lease.title is not None:
            current.setdefault("lease", {})["title"] = payload.lease.title
        if payload.lease.subtitle is not None:
            current.setdefault("lease", {})["subtitle"] = payload.lease.subtitle
    if payload.how_it_works is not None:
        current["how_it_works"] = [
            {
                "image_url": s.image_url or "",
                "label": s.label or "",
                "image_focus": (s.image_focus or "").strip() or "center",
            }
            for s in payload.how_it_works
        ]
    if payload.footer is not None:
        ft = current.setdefault("footer", {})
        if payload.footer.facebook_url is not None:
            ft["facebook_url"] = payload.footer.facebook_url
        if payload.footer.twitter_url is not None:
            ft["twitter_url"] = payload.footer.twitter_url
        if payload.footer.google_plus_url is not None:
            ft["google_plus_url"] = payload.footer.google_plus_url
        if payload.footer.instagram_url is not None:
            ft["instagram_url"] = payload.footer.instagram_url
        if payload.footer.youtube_url is not None:
            ft["youtube_url"] = payload.footer.youtube_url
        if payload.footer.address_line is not None:
            ft["address_line"] = payload.footer.address_line
        if payload.footer.phone_line is not None:
            ft["phone_line"] = payload.footer.phone_line
        if payload.footer.footer_disclosure is not None:
            ft["footer_disclosure"] = payload.footer.footer_disclosure
        if payload.footer.copyright_line is not None:
            ft["copyright_line"] = payload.footer.copyright_line
        if payload.footer.link_lease_label is not None:
            ft["link_lease_label"] = payload.footer.link_lease_label
        if payload.footer.link_lease_url is not None:
            ft["link_lease_url"] = payload.footer.link_lease_url
        if payload.footer.link_broker_label is not None:
            ft["link_broker_label"] = payload.footer.link_broker_label
        if payload.footer.link_broker_url is not None:
            ft["link_broker_url"] = payload.footer.link_broker_url
    row.content = json.dumps(current)
    db.commit()
    db.refresh(row)
    invalidate_landing_page_cache()
    return {"status": "updated", "content": current}


@router.get("/users", response_model=list[UserOut])
def admin_list_users(
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    rows = (
        db.query(User)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(500)
        .all()
    )
    return [UserOut.model_validate(row) for row in rows]


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_email_verified: Optional[bool] = None
    is_phone_verified: Optional[bool] = None


class AdminUserPasswordReset(BaseModel):
    new_password: str


@router.put("/users/{user_id}", response_model=UserOut)
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current=Depends(require_role("super_admin")),
):
    _ = current
    row = db.query(User).filter(User.id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    if payload.name is not None:
        cleaned = payload.name.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
        row.name = cleaned
    if payload.phone is not None:
        row.phone = payload.phone.strip() or None

    if payload.role is not None:
        role_value = payload.role.strip()
        if role_value not in {r.value for r in UserRole}:
            raise HTTPException(status_code=400, detail="Invalid role.")
        if row.role == UserRole.super_admin and role_value != UserRole.super_admin.value:
            remaining = (
                db.query(User)
                .filter(User.role == UserRole.super_admin, User.id != row.id)
                .count()
            )
            if remaining == 0:
                raise HTTPException(
                    status_code=400,
                    detail="At least one super_admin is required.",
                )
        row.role = UserRole(role_value)

    if payload.is_email_verified is not None:
        row.is_email_verified = bool(payload.is_email_verified)
    if payload.is_phone_verified is not None:
        row.is_phone_verified = bool(payload.is_phone_verified)

    db.commit()
    db.refresh(row)
    return UserOut.model_validate(row)


@router.post("/users/{user_id}/reset-password")
def admin_reset_user_password(
    user_id: int,
    payload: AdminUserPasswordReset,
    db: Session = Depends(get_db),
    current=Depends(require_role("super_admin")),
):
    _ = current
    row = db.query(User).filter(User.id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    new_password = (payload.new_password or "").strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    row.password_hash = hash_password(new_password)
    db.commit()
    return {"changed": True}


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current=Depends(require_role("super_admin")),
):
    row = db.query(User).filter(User.id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    if current.id == row.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    if row.role == UserRole.super_admin:
        remaining = (
            db.query(User)
            .filter(User.role == UserRole.super_admin, User.id != row.id)
            .count()
        )
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one super_admin is required.",
            )

    blockers: list[str] = []
    blocker_checks = [
        ("deals", db.query(func.count(Deal.id)).filter(Deal.user_id == row.id).scalar() or 0),
        ("broker messages", db.query(func.count(BrokerMessage.id)).filter(BrokerMessage.user_id == row.id).scalar() or 0),
        ("document submissions", db.query(func.count(DocumentSubmission.id)).filter(DocumentSubmission.user_id == row.id).scalar() or 0),
        ("favorites", db.query(func.count(Favorite.id)).filter(Favorite.user_id == row.id).scalar() or 0),
    ]
    for label, count in blocker_checks:
        if count:
            blockers.append(f"{label} ({int(count)})")

    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete user with linked records: " + ", ".join(blockers) + ".",
        )

    db.query(AuthOtp).filter(AuthOtp.user_id == row.id).delete(synchronize_session=False)
    db.query(LeadRequest).filter(LeadRequest.user_id == row.id).update(
        {LeadRequest.user_id: None},
        synchronize_session=False,
    )
    db.query(CreditApplication).filter(CreditApplication.user_id == row.id).update(
        {CreditApplication.user_id: None},
        synchronize_session=False,
    )
    db.query(CreditApplication).filter(CreditApplication.reviewed_by_user_id == row.id).update(
        {CreditApplication.reviewed_by_user_id: None},
        synchronize_session=False,
    )
    db.query(Deal).filter(Deal.assigned_broker_user_id == row.id).update(
        {Deal.assigned_broker_user_id: None},
        synchronize_session=False,
    )
    db.query(DealEvent).filter(DealEvent.actor_user_id == row.id).update(
        {DealEvent.actor_user_id: None},
        synchronize_session=False,
    )
    db.query(BrokerMessage).filter(BrokerMessage.broker_admin_user_id == row.id).update(
        {BrokerMessage.broker_admin_user_id: None},
        synchronize_session=False,
    )
    db.query(HomepageFeaturedVehicle).filter(HomepageFeaturedVehicle.updated_by_user_id == row.id).update(
        {HomepageFeaturedVehicle.updated_by_user_id: None},
        synchronize_session=False,
    )
    db.query(OfferOverride).filter(OfferOverride.updated_by_user_id == row.id).update(
        {OfferOverride.updated_by_user_id: None},
        synchronize_session=False,
    )

    db.delete(row)
    db.commit()
    return {"deleted": True}


# ---------- Testimonials (super_admin) ----------
class TestimonialUpsert(BaseModel):
    author: Optional[str] = None
    title: Optional[str] = None
    quote: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/testimonials")
def admin_list_testimonials(
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    rows = db.query(Testimonial).order_by(Testimonial.sort_order.asc(), Testimonial.id.asc()).all()
    return {
        "items": [
            {
                "id": int(row.id),
                "author": row.author,
                "title": row.title,
                "quote": row.quote,
                "image_url": getattr(row, "image_url", None),
                "sort_order": int(row.sort_order or 0),
            }
            for row in rows
        ]
    }


@router.post("/testimonials")
def admin_create_testimonial(
    payload: TestimonialUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    if not (payload.author or "").strip():
        raise HTTPException(status_code=400, detail="author is required.")
    if not (payload.quote or "").strip():
        raise HTTPException(status_code=400, detail="quote is required.")

    row = Testimonial(
        author=payload.author.strip(),
        quote=payload.quote.strip(),
        title=(payload.title.strip() if payload.title else None),
        image_url=(payload.image_url.strip() if payload.image_url else None),
        sort_order=int(payload.sort_order or 0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "status": "created",
        "item": {
            "id": int(row.id),
            "author": row.author,
            "title": row.title,
            "quote": row.quote,
            "image_url": getattr(row, "image_url", None),
            "sort_order": int(row.sort_order or 0),
        },
    }


@router.put("/testimonials/{testimonial_id}")
def admin_update_testimonial(
    testimonial_id: int,
    payload: TestimonialUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    row = db.query(Testimonial).filter(Testimonial.id == testimonial_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Testimonial not found.")

    if payload.author is not None:
        row.author = payload.author.strip()
    if payload.quote is not None:
        row.quote = payload.quote.strip()
    if payload.title is not None:
        row.title = payload.title.strip() if payload.title else None
    if payload.image_url is not None:
        row.image_url = payload.image_url.strip() if payload.image_url else None
    if payload.sort_order is not None:
        row.sort_order = int(payload.sort_order or 0)

    if not (row.author or "").strip():
        raise HTTPException(status_code=400, detail="author is required.")
    if not (row.quote or "").strip():
        raise HTTPException(status_code=400, detail="quote is required.")

    db.commit()
    db.refresh(row)
    return {
        "status": "updated",
        "item": {
            "id": int(row.id),
            "author": row.author,
            "title": row.title,
            "quote": row.quote,
            "image_url": getattr(row, "image_url", None),
            "sort_order": int(row.sort_order or 0),
        },
    }


@router.delete("/testimonials/{testimonial_id}")
def admin_delete_testimonial(
    testimonial_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    row = db.query(Testimonial).filter(Testimonial.id == testimonial_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Testimonial not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": testimonial_id}


# ---------- Articles (super_admin) ----------
class ArticleUpsert(BaseModel):
    title: str
    description: Optional[str] = None
    slug: str
    date: str  # YYYY-MM-DD
    content: str = ""


@router.get("/articles")
def admin_list_articles(
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    rows = db.query(Article).order_by(Article.date.desc(), Article.id.desc()).all()
    return {
        "items": [
            {
                "id": int(row.id),
                "title": row.title,
                "description": row.description,
                "slug": row.slug,
                "date": row.date,
                "content": row.content,
            }
            for row in rows
        ]
    }


@router.post("/articles")
def admin_create_article(
    payload: ArticleUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    title = (payload.title or "").strip()
    slug = (payload.slug or "").strip().lower().replace(" ", "-")
    if not title:
        raise HTTPException(status_code=400, detail="Title is required.")
    if not slug:
        raise HTTPException(status_code=400, detail="Slug is required.")
    if db.query(Article).filter(Article.slug == slug).first():
        raise HTTPException(status_code=400, detail="An article with this slug already exists.")
    date = (payload.date or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = Article(
        title=title,
        description=(payload.description or "").strip() or None,
        slug=slug,
        date=date,
        content=(payload.content or "").strip() or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "status": "created",
        "item": {
            "id": int(row.id),
            "title": row.title,
            "description": row.description,
            "slug": row.slug,
            "date": row.date,
            "content": row.content,
        },
    }


@router.put("/articles/{article_id}")
def admin_update_article(
    article_id: int,
    payload: ArticleUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    row = db.query(Article).filter(Article.id == article_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")
    title = (payload.title or "").strip()
    slug = (payload.slug or "").strip().lower().replace(" ", "-")
    if not title:
        raise HTTPException(status_code=400, detail="Title is required.")
    if not slug:
        raise HTTPException(status_code=400, detail="Slug is required.")
    existing = db.query(Article).filter(Article.slug == slug, Article.id != article_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Another article already has this slug.")
    row.title = title
    row.description = (payload.description or "").strip() or None
    row.slug = slug
    row.date = (payload.date or "").strip() or row.date
    row.content = (payload.content or "").strip() or ""
    db.commit()
    db.refresh(row)
    return {
        "status": "updated",
        "item": {
            "id": int(row.id),
            "title": row.title,
            "description": row.description,
            "slug": row.slug,
            "date": row.date,
            "content": row.content,
        },
    }


@router.delete("/articles/{article_id}")
def admin_delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("super_admin")),
):
    _ = user
    row = db.query(Article).filter(Article.id == article_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": article_id}


@router.get("/offer-overrides")
def list_offer_overrides(
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    query = db.query(OfferOverride)
    if source in {"sheet", "dealer", "broker"}:
        query = query.filter(OfferOverride.source == source)
    if q:
        query = query.filter(OfferOverride.vin.ilike(f"%{q.strip()}%"))
    rows = query.order_by(OfferOverride.updated_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "vin": row.vin,
                "source": row.source.value if hasattr(row.source, "value") else row.source,
                "down_payment": float(row.down_payment) if row.down_payment is not None else None,
                "monthly_payment": float(row.monthly_payment) if row.monthly_payment is not None else None,
                "discounted_price": float(row.discounted_price) if row.discounted_price is not None else None,
                "term_months": int(row.term_months) if row.term_months is not None else None,
                "miles_per_year": int(row.miles_per_year) if row.miles_per_year is not None else None,
                "updated_at": str(row.updated_at) if row.updated_at else None,
            }
            for row in rows
        ]
    }


@router.put("/offer-overrides/{vin}")
def upsert_offer_override(
    vin: str,
    payload: OfferOverrideUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    normalized_vin = _normalize_vin(vin)
    row = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not row:
        row = OfferOverride(vin=normalized_vin, source=OfferSource.broker, updated_by_user_id=user.id)
        db.add(row)

    row.down_payment = payload.down_payment
    row.monthly_payment = payload.monthly_payment
    row.discounted_price = payload.discounted_price
    row.term_months = payload.term_months
    row.miles_per_year = payload.miles_per_year
    row.source = OfferSource.broker
    row.updated_by_user_id = user.id
    set_offer_visibility(row)
    db.commit()
    db.refresh(row)

    return {
        "status": "updated",
        "vin": row.vin,
        "source": row.source.value if hasattr(row.source, "value") else row.source,
        "down_payment": float(row.down_payment) if row.down_payment is not None else None,
        "monthly_payment": float(row.monthly_payment) if row.monthly_payment is not None else None,
        "discounted_price": float(row.discounted_price) if row.discounted_price is not None else None,
        "term_months": int(row.term_months) if row.term_months is not None else None,
        "miles_per_year": int(row.miles_per_year) if row.miles_per_year is not None else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@router.delete("/offer-overrides/{vin}")
def delete_offer_override(
    vin: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    normalized_vin = _normalize_vin(vin)
    row = db.query(OfferOverride).filter(OfferOverride.vin == normalized_vin).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer override not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "vin": normalized_vin}


@router.put("/offer-overrides-by-ymm")
def upsert_offer_override_by_ymm(
    payload: OfferOverrideYmmUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("broker_admin")),
):
    filters = {
        "year": payload.year,
        "make": payload.make,
        "model": payload.model,
    }
    if payload.vehicle_type in {"new", "used", "all"}:
        filters["vehicle_type"] = payload.vehicle_type

    rows = db.execute(build_inventory_query(engine, filters)).fetchall()
    vins = sorted(
        {
            str(row._mapping.get("vin")).strip().upper()
            for row in rows
            if row._mapping.get("vin")
        }
    )
    if not vins:
        raise HTTPException(status_code=404, detail="No vehicles found for year/make/model.")

    for vin in vins:
        row = db.query(OfferOverride).filter(OfferOverride.vin == vin).first()
        if not row:
            row = OfferOverride(vin=vin, source=OfferSource.broker, updated_by_user_id=user.id)
            db.add(row)
        row.down_payment = payload.down_payment
        row.monthly_payment = payload.monthly_payment
        row.discounted_price = payload.discounted_price
        row.term_months = payload.term_months
        row.miles_per_year = payload.miles_per_year
        row.source = OfferSource.broker
        row.updated_by_user_id = user.id
        set_offer_visibility(row)

    db.commit()
    return {
        "status": "updated",
        "updated_count": len(vins),
        "year": payload.year,
        "make": payload.make,
        "model": payload.model,
        "vins": vins[:200],
    }
