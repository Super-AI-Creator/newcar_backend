from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String, func

from app.models.base import Base


class LenderRate(Base):
    __tablename__ = "lender_rates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lender_name = Column(String(120), nullable=False, index=True)
    credit_tier = Column(String(20), nullable=False, index=True)
    vehicle_type = Column(String(20), nullable=False, index=True, default="all")
    apr = Column(Numeric(6, 3), nullable=False)
    max_term_months = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
