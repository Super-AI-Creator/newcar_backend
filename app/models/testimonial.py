from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class Testimonial(Base):
    __tablename__ = "testimonials"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=True)
    quote = Column(Text, nullable=False)
    author = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
