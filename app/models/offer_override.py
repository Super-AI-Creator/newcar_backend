from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Numeric, String, func
from app.models.base import Base
from app.models.enums import OfferSource


class OfferOverride(Base):
    __tablename__ = "offer_overrides"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    vin = Column(String(17), unique=True, nullable=False, index=True)
    down_payment = Column(Numeric(12, 2), nullable=True)
    monthly_payment = Column(Numeric(12, 2), nullable=True)
    discounted_price = Column(Numeric(12, 2), nullable=True)
    term_months = Column(BigInteger, nullable=True)
    miles_per_year = Column(BigInteger, nullable=True)
    visible_down_payment = Column(Boolean, nullable=False, default=False)
    visible_monthly = Column(Boolean, nullable=False, default=False)
    visible_discounted = Column(Boolean, nullable=False, default=False)
    source = Column(Enum(OfferSource), nullable=False, index=True)
    updated_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
