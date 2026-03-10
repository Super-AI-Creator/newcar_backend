from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text, func

from app.models.base import Base


class ManualVehicle(Base):
    __tablename__ = "manual_vehicles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    vin = Column(String(32), nullable=False, unique=True, index=True)
    vehicle_type = Column(String(10), nullable=False, server_default="new")
    year = Column(Integer, nullable=True)
    make = Column(String(100), nullable=True)
    model = Column(String(120), nullable=True)
    trim = Column(String(120), nullable=True)
    msrp = Column(Float, nullable=True)
    listed_price = Column(Float, nullable=True)
    mileage = Column(Integer, nullable=True)
    condition = Column(String(20), nullable=True)
    details_json = Column(Text, nullable=True)
    photos_json = Column(Text, nullable=True)
    dealer_name = Column(String(160), nullable=True)
    dealer_phone = Column(String(40), nullable=True)
    listing_url = Column(String(500), nullable=True)
    carfax_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")
    updated_by_user_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
