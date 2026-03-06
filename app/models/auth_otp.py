from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, func
from app.models.base import Base
from app.models.enums import OtpChannel


class AuthOtp(Base):
    __tablename__ = "auth_otps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(Enum(OtpChannel), nullable=False)
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
