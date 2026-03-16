from sqlalchemy import BigInteger, Column, DateTime, Text, func

from app.models.base import Base


class LandingPageContent(Base):
    __tablename__ = "landing_page_content"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=True)  # JSON: hero, lease, how_it_works
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
