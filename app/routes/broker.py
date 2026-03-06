from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.broker_message import BrokerMessage
from app.schemas.misc import BrokerMessageIn, BrokerReplyIn
from app.services.broker_messages import encode_message_for_storage
from app.services.broker_routing import select_next_broker_admin_user_id

router = APIRouter(prefix="/broker", tags=["broker"])


@router.post("/message")
def send_message(payload: BrokerMessageIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    assigned_broker_user_id = select_next_broker_admin_user_id(db)
    msg = BrokerMessage(
        user_id=user.id,
        vin=payload.vin,
        message_text=encode_message_for_storage(payload.message_text, sender_type="customer"),
        broker_admin_user_id=assigned_broker_user_id,
    )
    db.add(msg)
    db.commit()
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
