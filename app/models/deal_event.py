from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text, func

from app.models.base import Base


class DealEvent(Base):
    __tablename__ = "deal_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    deal_id = Column(BigInteger, ForeignKey("deals.id"), nullable=False, index=True)
    actor_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
