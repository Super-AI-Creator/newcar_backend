from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.deal import Deal
from app.models.deal_event import DealEvent
from app.models.enums import DealStatus
from app.models.user import User
from app.schemas.deals import DealCreateIn, DealEventOut, DealOut, DealUpdateIn

router = APIRouter(prefix="/deals", tags=["deals"])

ALLOWED_TRANSITIONS: dict[DealStatus, set[DealStatus]] = {
    DealStatus.inquiry: {DealStatus.broker_review, DealStatus.cancelled},
    DealStatus.broker_review: {DealStatus.offer_ready, DealStatus.cancelled},
    DealStatus.offer_ready: {DealStatus.locked, DealStatus.cancelled},
    DealStatus.locked: {DealStatus.docs_pending, DealStatus.cancelled},
    DealStatus.docs_pending: {DealStatus.delivered, DealStatus.cancelled},
    DealStatus.delivered: set(),
    DealStatus.cancelled: set(),
}


def _serialize_deal(row: Deal) -> DealOut:
    status_value = row.status.value if hasattr(row.status, "value") else str(row.status)
    return DealOut(
        id=int(row.id),
        user_id=int(row.user_id),
        vin=row.vin,
        status=status_value,
        customer_note=row.customer_note,
        broker_note=row.broker_note,
        assigned_broker_user_id=int(row.assigned_broker_user_id) if row.assigned_broker_user_id is not None else None,
        delivery_scheduled_at=str(row.delivery_scheduled_at) if row.delivery_scheduled_at else None,
        delivery_address=row.delivery_address,
        delivery_city=row.delivery_city,
        delivery_state=row.delivery_state,
        delivery_zip=row.delivery_zip,
        delivery_notes=row.delivery_notes,
        locked_at=str(row.locked_at) if row.locked_at else None,
        delivered_at=str(row.delivered_at) if row.delivered_at else None,
        created_at=str(row.created_at) if row.created_at else None,
        updated_at=str(row.updated_at) if row.updated_at else None,
    )


def _serialize_event(row: DealEvent) -> DealEventOut:
    return DealEventOut(
        id=int(row.id),
        deal_id=int(row.deal_id),
        actor_user_id=int(row.actor_user_id) if row.actor_user_id is not None else None,
        event_type=row.event_type,
        message=row.message,
        created_at=str(row.created_at) if row.created_at else None,
    )


def _log_event(
    db: Session,
    deal_id: int,
    event_type: str,
    actor_user_id: Optional[int] = None,
    message: Optional[str] = None,
):
    row = DealEvent(
        deal_id=deal_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        message=message,
    )
    db.add(row)


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid datetime format") from exc


@router.post("", response_model=DealOut)
def create_deal(payload: DealCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    vin = payload.vin.strip().upper()
    existing = (
        db.query(Deal)
        .filter(
            Deal.user_id == user.id,
            Deal.vin == vin,
            Deal.status.in_(
                [
                    DealStatus.inquiry,
                    DealStatus.broker_review,
                    DealStatus.offer_ready,
                    DealStatus.locked,
                    DealStatus.docs_pending,
                ]
            ),
        )
        .order_by(Deal.created_at.desc())
        .first()
    )
    if existing:
        return _serialize_deal(existing)

    row = Deal(
        user_id=user.id,
        vin=vin,
        status=DealStatus.inquiry,
        customer_note=payload.customer_note.strip() if payload.customer_note else None,
    )
    db.add(row)
    db.flush()
    _log_event(
        db,
        deal_id=int(row.id),
        actor_user_id=int(user.id),
        event_type="deal_created",
        message=f"Customer started deal for VIN {vin}",
    )
    db.commit()
    db.refresh(row)
    return _serialize_deal(row)


@router.get("/mine")
def list_my_deals(
    status: Optional[str] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Deal).filter(Deal.user_id == user.id)
    if status:
        try:
            status_enum = DealStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status") from exc
        query = query.filter(Deal.status == status_enum)
    rows = query.order_by(Deal.updated_at.desc(), Deal.created_at.desc()).all()
    return {"items": [_serialize_deal(row).dict() for row in rows]}


@router.get("")
def list_all_deals(
    status: Optional[str] = Query(None),
    user=Depends(require_role("broker_admin")),
    db: Session = Depends(get_db),
):
    _ = user
    query = db.query(Deal)
    if status:
        try:
            status_enum = DealStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status") from exc
        query = query.filter(Deal.status == status_enum)
    rows = query.order_by(Deal.updated_at.desc(), Deal.created_at.desc()).limit(500).all()
    return {"items": [_serialize_deal(row).dict() for row in rows]}


@router.patch("/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: int,
    payload: DealUpdateIn,
    user=Depends(require_role("broker_admin")),
    db: Session = Depends(get_db),
):
    _ = user
    row = db.query(Deal).filter(Deal.id == deal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found")

    if payload.status is not None:
        try:
            next_status = DealStatus(payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status") from exc
        current_status = row.status if isinstance(row.status, DealStatus) else DealStatus(str(row.status))
        if next_status != current_status and next_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition from {current_status.value} to {next_status.value}",
            )
        row.status = next_status
        _log_event(
            db,
            deal_id=int(row.id),
            actor_user_id=int(user.id),
            event_type="status_changed",
            message=f"Status changed to {next_status.value}",
        )
        if next_status == DealStatus.locked and row.locked_at is None:
            row.locked_at = datetime.utcnow()
        if next_status == DealStatus.delivered and row.delivered_at is None:
            row.delivered_at = datetime.utcnow()

    if payload.broker_note is not None:
        row.broker_note = payload.broker_note.strip() or None

    if payload.assigned_broker_email is not None:
        normalized_email = payload.assigned_broker_email.strip().lower()
        if not normalized_email:
            row.assigned_broker_user_id = None
            _log_event(
                db,
                deal_id=int(row.id),
                actor_user_id=int(user.id),
                event_type="broker_unassigned",
                message="Assigned broker cleared",
            )
        else:
            broker_user = db.query(User).filter(User.email == normalized_email).first()
            if not broker_user:
                raise HTTPException(status_code=404, detail="Assigned broker email not found")
            broker_role = broker_user.role.value if hasattr(broker_user.role, "value") else str(broker_user.role)
            if broker_role not in {"broker_admin", "admin"}:
                raise HTTPException(status_code=400, detail="Assigned user must be broker admin")
            row.assigned_broker_user_id = int(broker_user.id)
            _log_event(
                db,
                deal_id=int(row.id),
                actor_user_id=int(user.id),
                event_type="broker_assigned",
                message=f"Assigned to broker {broker_user.email}",
            )
    elif payload.assigned_broker_user_id is not None:
        broker_user = db.query(User).filter(User.id == payload.assigned_broker_user_id).first()
        if not broker_user:
            raise HTTPException(status_code=404, detail="Assigned broker user not found")
        broker_role = broker_user.role.value if hasattr(broker_user.role, "value") else str(broker_user.role)
        if broker_role not in {"broker_admin", "admin"}:
            raise HTTPException(status_code=400, detail="Assigned user must be broker admin")
        row.assigned_broker_user_id = int(broker_user.id)
        _log_event(
            db,
            deal_id=int(row.id),
            actor_user_id=int(user.id),
            event_type="broker_assigned",
            message=f"Assigned to broker user {broker_user.id}",
        )

    if payload.delivery_scheduled_at is not None:
        row.delivery_scheduled_at = _parse_optional_datetime(payload.delivery_scheduled_at)
        _log_event(
            db,
            deal_id=int(row.id),
            actor_user_id=int(user.id),
            event_type="delivery_scheduled",
            message=f"Delivery scheduled at {row.delivery_scheduled_at}" if row.delivery_scheduled_at else "Delivery schedule cleared",
        )
    if payload.delivery_address is not None:
        row.delivery_address = payload.delivery_address.strip() or None
    if payload.delivery_city is not None:
        row.delivery_city = payload.delivery_city.strip() or None
    if payload.delivery_state is not None:
        row.delivery_state = payload.delivery_state.strip() or None
    if payload.delivery_zip is not None:
        row.delivery_zip = payload.delivery_zip.strip() or None
    if payload.delivery_notes is not None:
        row.delivery_notes = payload.delivery_notes.strip() or None

    db.commit()
    db.refresh(row)
    return _serialize_deal(row)


@router.get("/{deal_id}/events")
def deal_events(
    deal_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if role_value not in {"broker_admin", "admin"} and int(deal.user_id) != int(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = (
        db.query(DealEvent)
        .filter(DealEvent.deal_id == deal_id)
        .order_by(DealEvent.created_at.asc(), DealEvent.id.asc())
        .all()
    )
    return {"items": [_serialize_event(row).dict() for row in rows]}


@router.get("/queue")
def broker_queue(
    status: Optional[str] = Query(None),
    user=Depends(require_role("broker_admin")),
    db: Session = Depends(get_db),
):
    _ = user
    query = db.query(Deal)
    if status:
        try:
            status_enum = DealStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status") from exc
        query = query.filter(Deal.status == status_enum)
    rows = query.order_by(Deal.updated_at.desc(), Deal.created_at.desc()).limit(500).all()
    user_ids = sorted(
        {
            int(row.user_id)
            for row in rows
            if row.user_id is not None
        }
        | {
            int(row.assigned_broker_user_id)
            for row in rows
            if row.assigned_broker_user_id is not None
        }
    )
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {int(u.id): u for u in users}

    items = []
    for row in rows:
        customer = user_map.get(int(row.user_id))
        assigned_broker = user_map.get(int(row.assigned_broker_user_id)) if row.assigned_broker_user_id is not None else None
        deal = _serialize_deal(row).dict()
        deal["customer_name"] = customer.name if customer else None
        deal["customer_email"] = customer.email if customer else None
        deal["customer_phone"] = customer.phone if customer else None
        deal["assigned_broker_email"] = assigned_broker.email if assigned_broker else None
        deal["assigned_broker_name"] = assigned_broker.name if assigned_broker else None
        items.append(deal)
    return {"items": items}
