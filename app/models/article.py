from sqlalchemy import BigInteger, Column, DateTime, String, Text, func

from app.models.base import Base


class Article(Base):
    __tablename__ = "articles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    description = Column(String(1000), nullable=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
