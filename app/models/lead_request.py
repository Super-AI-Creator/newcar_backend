from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.models.base import Base


class LeadRequest(Base):
    __tablename__ = "lead_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    vin = Column(String(17), nullable=True, index=True)
    year = Column(Integer, nullable=True)
    make = Column(String(120), nullable=True)
    model = Column(String(120), nullable=True)
    trim = Column(String(160), nullable=True)
    vehicle = Column(String(255), nullable=True)
    name = Column(String(160), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(60), nullable=False)
    notes = Column(Text, nullable=True)
    source = Column(String(120), nullable=True, index=True)
    webhook_status = Column(String(30), nullable=False, server_default="pending", index=True)
    webhook_attempts = Column(Integer, nullable=False, server_default="0")
    webhook_last_error = Column(Text, nullable=True)
    webhook_last_attempt_at = Column(DateTime, nullable=True)
    webhook_delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
