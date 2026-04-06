from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, Text, func

from app.models.base import Base
from app.models.enums import DealStatus


class Deal(Base):
    __tablename__ = "deals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    assigned_broker_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    vin = Column(String(17), nullable=False, index=True)
    status = Column(Enum(DealStatus), nullable=False, index=True, default=DealStatus.inquiry)
    customer_note = Column(Text, nullable=True)
    broker_note = Column(Text, nullable=True)
    credit_union_id = Column(
        BigInteger, ForeignKey("credit_unions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cu_approval_id = Column(
        BigInteger, ForeignKey("cu_member_approvals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delivery_scheduled_at = Column(DateTime, nullable=True)
    delivery_address = Column(String(255), nullable=True)
    delivery_city = Column(String(120), nullable=True)
    delivery_state = Column(String(120), nullable=True)
    delivery_zip = Column(String(30), nullable=True)
    delivery_notes = Column(Text, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
