from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, Boolean, func
from app.models.base import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), nullable=False, index=True)
    credit_union_id = Column(BigInteger, ForeignKey("credit_unions.id", ondelete="SET NULL"), nullable=True, index=True)
    # carscu.com vs newcarsuperstore.com — see app.core.auth_realm
    auth_realm = Column(String(64), nullable=True, index=True)
    is_phone_verified = Column(Boolean, nullable=False, default=False)
    is_email_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
