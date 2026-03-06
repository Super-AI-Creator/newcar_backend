from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_current_user, get_db, require_role
from app.models.broker_message import BrokerMessage
from app.models.credit_application import CreditApplication
from app.models.offer_override import OfferOverride
from app.models.user import User
from app.services.broker_messages import encode_message_for_storage, parse_message_from_storage
from app.services.broker_routing import select_next_broker_admin_user_id
from app.services.legacy_tables import build_inventory_count_query, build_inventory_query, load_legacy_tables, serialize_photos

router = APIRouter(tags=["frontend-compat"])


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dealer_source_ids(db: Session, user_email: str) -> list[int]:
    tables = load_legacy_tables(engine)
    dealer_sources = tables["dealer_sources"]
    normalized_email = (user_email or "").strip().lower()
    source_ids: list[int] = []
    email_columns = [col_name for col_name in ["email", "contact_email", "dealer_email"] if col_name in dealer_sources.c]

    for col_name in email_columns:
        col = dealer_sources.c[col_name]
        if col_name in dealer_sources.c:
            rows = db.execute(
                select(dealer_sources.c.id).where(func.lower(func.trim(col)) == normalized_email)
            ).fetchall()
            source_ids.extend([int(row[0]) for row in rows])

    # Fallback for schemas without dealer contact columns:
    # expose enabled sources to dealer users rather than returning an empty inventory.
    if not source_ids and not email_columns:
        base = select(dealer_sources.c.id)
        if "enabled" in dealer_sources.c:
            base = base.where(dealer_sources.c.enabled == True)
        rows = db.execute(base).fetchall()
        source_ids.extend([int(row[0]) for row in rows])
    return sorted(set(source_ids))


@router.get("/messages")
def list_messages(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    query = db.query(BrokerMessage)
    if role_value not in {"broker_admin", "admin"}:
        query = query.filter(BrokerMessage.user_id == user.id)
    rows = query.order_by(BrokerMessage.created_at.desc()).all()
    broker_user_ids = sorted(
        {
            int(row.broker_admin_user_id)
            for row in rows
            if row.broker_admin_user_id is not None
        }
    )
    broker_users = db.query(User).filter(User.id.in_(broker_user_ids)).all() if broker_user_ids else []
    broker_map = {int(b.id): b for b in broker_users}
    customer_user_ids = sorted({int(row.user_id) for row in rows if row.user_id is not None})
    customer_users = db.query(User).filter(User.id.in_(customer_user_ids)).all() if customer_user_ids else []
    customer_map = {int(c.id): c for c in customer_users}
    items = []
    for row in rows:
        sender_type, body = parse_message_from_storage(row.message_text)
        broker_user = broker_map.get(int(row.broker_admin_user_id)) if row.broker_admin_user_id is not None else None
        customer_user = customer_map.get(int(row.user_id)) if row.user_id is not None else None
        items.append(
            {
                "id": str(row.id),
                "vin": row.vin,
                "body": body,
                "senderType": sender_type,
                "createdAt": str(row.created_at) if row.created_at else None,
                "userId": str(row.user_id) if row.user_id is not None else None,
                "customerName": customer_user.name if customer_user else None,
                "customerEmail": customer_user.email if customer_user else None,
                "brokerAdminUserId": str(row.broker_admin_user_id) if row.broker_admin_user_id is not None else None,
                "brokerAdminEmail": broker_user.email if broker_user else None,
            }
        )
    return {"items": items}


@router.post("/messages")
def send_message_compat(
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message_text = (payload or {}).get("message")
    if not isinstance(message_text, str) or not message_text.strip():
        raise HTTPException(status_code=400, detail="message is required")

    vin = (payload or {}).get("vin")
    assigned_broker_user_id = select_next_broker_admin_user_id(db)
    msg = BrokerMessage(
        user_id=user.id,
        vin=vin,
        message_text=encode_message_for_storage(message_text, sender_type="customer"),
        broker_admin_user_id=assigned_broker_user_id,
    )
    db.add(msg)
    db.commit()
    return {"sent": True, "broker_admin_user_id": assigned_broker_user_id}


@router.post("/credit-applications")
def credit_application_compat(
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    vin = (payload or {}).get("vin")
    row = CreditApplication(
        user_id=user.id,
        vin=vin,
        payload_json=payload or {},
        source="compat",
        status="submitted",
    )
    db.add(row)
    db.commit()
    return {"submitted": True}


@router.get("/dealer/inventory")
def dealer_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_total: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(require_role("dealer")),
):
    # All vehicles, paginated.
    # `include_total=false` avoids a full-count scan on every page load.
    filters = {"vehicle_type": "all"}
    base = build_inventory_query(engine, filters)
    query = base.offset((page - 1) * page_size).limit(page_size + 1)
    rows = db.execute(query).fetchall()
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]

    total: Optional[int] = None
    if include_total:
        total = db.execute(build_inventory_count_query(engine, filters)).scalar() or 0
    vins = [row._mapping.get("vin") for row in rows if row._mapping.get("vin")]
    offer_map: dict[str, OfferOverride] = {}
    if vins:
        offers = db.query(OfferOverride).filter(OfferOverride.vin.in_(vins)).all()
        offer_map = {str(offer.vin): offer for offer in offers}

    items = []
    for row in rows:
        m = row._mapping
        vin = str(m.get("vin") or "")
        offer = offer_map.get(vin)
        item = {
            "vin": vin,
            "vehicle_type": (m.get("vehicle_type") or "").lower() or None,
            "year": m.get("year"),
            "make": m.get("make"),
            "model": m.get("model"),
            "trim": m.get("trim"),
            "msrp": _to_float(m.get("msrp")),
            "listed_price": _to_float(m.get("listed_price")),
            "mileage": m.get("mileage"),
            "condition": str(m.get("condition")).lower() if m.get("condition") else None,
            "photos": serialize_photos(m.get("photos")),
            "last_seen_at": str(m.get("last_seen_at")) if m.get("last_seen_at") else None,
            "down": _to_float(offer.down_payment) if offer else None,
            "monthly": _to_float(offer.monthly_payment) if offer else None,
            "discounted": _to_float(offer.discounted_price) if offer else None,
            "term_months": int(offer.term_months) if offer and offer.term_months is not None else None,
            "miles_per_year": int(offer.miles_per_year) if offer and offer.miles_per_year is not None else None,
        }
        items.append(item)

    return {"items": items, "total": total, "has_more": has_more, "page": page, "page_size": page_size}
