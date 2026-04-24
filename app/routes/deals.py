from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.credit_union import CreditUnion, CuMemberApproval
from app.models.deal import Deal
from app.models.deal_event import DealEvent
from app.models.enums import DealStatus
from app.models.user import User
from app.schemas.deals import DealCreateIn, DealEventOut, DealOut, DealUpdateIn
from app.services.cu_member_scope import resolve_member_scope_user_id
from app.services.lead_delivery import send_lead_webhook

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
        credit_union_id=int(row.credit_union_id) if getattr(row, "credit_union_id", None) is not None else None,
    )


def _batch_cu_approval_maps(db: Session, rows: list) -> tuple[dict, dict]:
    cu_ids = {int(r.credit_union_id) for r in rows if getattr(r, "credit_union_id", None) is not None}
    ap_ids = {int(r.cu_approval_id) for r in rows if getattr(r, "cu_approval_id", None) is not None}
    cu_map = {int(c.id): c for c in db.query(CreditUnion).filter(CreditUnion.id.in_(cu_ids)).all()} if cu_ids else {}
    ap_map = {
        int(a.id): a for a in db.query(CuMemberApproval).filter(CuMemberApproval.id.in_(ap_ids)).all()
    } if ap_ids else {}
    return cu_map, ap_map


def _deal_dict_with_cu(
    db: Session,
    row: Deal,
    cu_map: Optional[dict] = None,
    ap_map: Optional[dict] = None,
) -> dict:
    if cu_map is None or ap_map is None:
        cu_map, ap_map = _batch_cu_approval_maps(db, [row])
    d = _serialize_deal(row).dict()
    cu_id = getattr(row, "credit_union_id", None)
    ap_id = getattr(row, "cu_approval_id", None)
    cu = cu_map.get(int(cu_id)) if cu_id is not None else None
    ap = ap_map.get(int(ap_id)) if ap_id is not None else None
    d["credit_union_name"] = cu.name if cu else None
    d["approval_amount"] = float(ap.loan_amount) if ap is not None and ap.loan_amount is not None else None
    return d


def _deals_list_items(
    db: Session,
    rows: list,
    cu_map: Optional[dict] = None,
    ap_map: Optional[dict] = None,
) -> list:
    if not rows:
        return []
    if cu_map is None or ap_map is None:
        cu_map, ap_map = _batch_cu_approval_maps(db, rows)
    return [_deal_dict_with_cu(db, r, cu_map, ap_map) for r in rows]


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
def create_deal(
    payload: DealCreateIn,
    member_user_id: Optional[int] = Query(None),
    background_tasks: BackgroundTasks = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    vin = payload.vin.strip().upper()
    existing = (
        db.query(Deal)
        .filter(
            Deal.user_id == scoped_user_id,
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
        return _deal_dict_with_cu(db, existing)

    row = Deal(
        user_id=scoped_user_id,
        vin=vin,
        status=DealStatus.inquiry,
        customer_note=payload.customer_note.strip() if payload.customer_note else None,
    )

    # Attach latest active/pending CU approval for this user, if any.
    approval = (
        db.query(CuMemberApproval)
        .filter(
            CuMemberApproval.user_id == scoped_user_id,
            CuMemberApproval.status.in_(["pending", "active", "funded"]),
        )
        .order_by(CuMemberApproval.created_at.desc())
        .first()
    )
    if approval:
        row.credit_union_id = approval.credit_union_id
        row.cu_approval_id = approval.id
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
    if background_tasks is not None:
        background_tasks.add_task(
            send_lead_webhook,
            {
                "event": "deal.created",
                "deal_id": int(row.id),
                "user_id": int(row.user_id),
                "vin": row.vin,
                "status": row.status.value if hasattr(row.status, "value") else str(row.status),
                "customer_note": row.customer_note,
                "customer_email": getattr(user, "email", None),
                "customer_name": getattr(user, "name", None),
                "source": "deal_creation",
                "created_at": str(row.created_at) if row.created_at else None,
            },
        )
    return _deal_dict_with_cu(db, row)


@router.get("/mine")
def list_my_deals(
    status: Optional[str] = Query(None),
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    query = db.query(Deal).filter(Deal.user_id == scoped_user_id)
    if status:
        try:
            status_enum = DealStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status") from exc
        query = query.filter(Deal.status == status_enum)
    rows = query.order_by(Deal.updated_at.desc(), Deal.created_at.desc()).all()
    return {"items": _deals_list_items(db, rows)}


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
    return {"items": _deals_list_items(db, rows)}


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
    return _deal_dict_with_cu(db, row)


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

    cu_map, ap_map = _batch_cu_approval_maps(db, rows)
    items = _deals_list_items(db, rows, cu_map, ap_map)
    for i, row in enumerate(rows):
        deal = items[i]
        customer = user_map.get(int(row.user_id))
        assigned_broker = (
            user_map.get(int(row.assigned_broker_user_id)) if row.assigned_broker_user_id is not None else None
        )
        cu = cu_map.get(int(row.credit_union_id)) if getattr(row, "credit_union_id", None) is not None else None

        if cu:
            # CU deal: mask email/phone, keep only first name
            first_name = (customer.name or "").split()[0] if customer and customer.name else None
            deal["customer_name"] = first_name
            deal["customer_email"] = None
            deal["customer_phone"] = None
        else:
            deal["customer_name"] = customer.name if customer else None
            deal["customer_email"] = customer.email if customer else None
            deal["customer_phone"] = customer.phone if customer else None

        deal["assigned_broker_email"] = assigned_broker.email if assigned_broker else None
        deal["assigned_broker_name"] = assigned_broker.name if assigned_broker else None
        items.append(deal)
    return {"items": items}
