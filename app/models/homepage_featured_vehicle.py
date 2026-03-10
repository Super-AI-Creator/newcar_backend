from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.models.base import Base


class HomepageFeaturedVehicle(Base):
    __tablename__ = "homepage_featured_vehicles"
    __table_args__ = (
        UniqueConstraint("month_key", "position", name="uq_homepage_featured_month_position"),
        UniqueConstraint("month_key", "vin", name="uq_homepage_featured_month_vin"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    month_key = Column(String(7), nullable=False, index=True)  # YYYY-MM
    position = Column(Integer, nullable=False)  # 1..6
    vin = Column(String(32), nullable=False)
    updated_by_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
