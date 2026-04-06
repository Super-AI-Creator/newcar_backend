import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.broker_message import BrokerMessage
from app.models.user import User
from app.schemas.misc import BrokerMessageIn, BrokerReplyIn
from app.services.broker_messages import encode_message_for_storage, parse_message_from_storage
from app.services.ghl_deal_room import sync_deal_room_customer_message_to_ghl
from app.services.broker_message_webhook import (
    is_broker_message_webhook_enabled,
    run_broker_customer_message_webhook_task,
)
from app.services.broker_routing import select_next_broker_admin_user_id
from app.services.cu_member_scope import resolve_member_scope_user_id

router = APIRouter(prefix="/broker", tags=["broker"])
logger = logging.getLogger(__name__)


@router.post("/message")
def send_message(
    payload: BrokerMessageIn,
    background_tasks: BackgroundTasks,
    member_user_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scoped_user_id = resolve_member_scope_user_id(db, user, member_user_id)
    assigned_broker_user_id = select_next_broker_admin_user_id(db)
    msg = BrokerMessage(
        user_id=scoped_user_id,
        vin=payload.vin,
        message_text=encode_message_for_storage(payload.message_text, sender_type="customer"),
        broker_admin_user_id=assigned_broker_user_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    message_user = user
    if int(scoped_user_id) != int(user.id):
        target_user = db.query(User).filter(User.id == int(scoped_user_id)).first()
        if target_user is not None:
            message_user = target_user
    try:
        _, body = parse_message_from_storage(msg.message_text or "")
        sync_deal_room_customer_message_to_ghl(user=message_user, message_text=body, vin=msg.vin)
    except Exception:
        logger.exception("GHL deal room sync failed after save message_id=%s", msg.id)
    if is_broker_message_webhook_enabled():
        background_tasks.add_task(run_broker_customer_message_webhook_task, int(msg.id))
    return {"status": "sent", "broker_admin_user_id": assigned_broker_user_id}


@router.post("/reply")
def reply_to_customer(payload: BrokerReplyIn, user=Depends(require_role("broker_admin")), db: Session = Depends(get_db)):
    msg = BrokerMessage(
        user_id=payload.customer_user_id,
        vin=payload.vin,
        message_text=encode_message_for_storage(payload.message_text, sender_type="broker"),
        broker_admin_user_id=user.id,
    )
    db.add(msg)
    db.commit()
    return {"status": "sent", "broker_admin_user_id": user.id}
