from sqlalchemy import BigInteger, Column, DateTime, String, Text, func

from app.models.base import Base


class CuDemoContact(Base):
    __tablename__ = "cu_demo_contacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    cu_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(80), nullable=True)
    message = Column(Text(), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
