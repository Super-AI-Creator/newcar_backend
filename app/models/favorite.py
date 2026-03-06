from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from app.models.base import Base


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "vin", name="uq_favorites_user_vin"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    vin = Column(String(17), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
