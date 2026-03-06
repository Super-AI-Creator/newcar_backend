from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func
from app.models.base import Base


class BrokerMessage(Base):
    __tablename__ = "broker_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    vin = Column(String(17), nullable=True, index=True)
    message_text = Column(String(2000), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    broker_admin_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
