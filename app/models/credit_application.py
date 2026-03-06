from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, JSON, String, Text, func
from app.models.base import Base


class CreditApplication(Base):
    __tablename__ = "credit_applications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    vin = Column(String(17), nullable=True, index=True)
    source = Column(String(30), nullable=False, server_default="authenticated", index=True)
    status = Column(String(30), nullable=False, server_default="submitted", index=True)
    broker_note = Column(Text, nullable=True)
    reviewed_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
