from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, Text, func

from app.models.base import Base


class SeoPageSetting(Base):
    __tablename__ = "seo_page_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    page_key = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=True)
    description = Column(String(500), nullable=True)
    keywords = Column(String(1000), nullable=True)
    canonical_url = Column(String(500), nullable=True)
    og_title = Column(String(255), nullable=True)
    og_description = Column(String(500), nullable=True)
    og_image_url = Column(String(500), nullable=True)
    robots = Column(String(120), nullable=True)
    json_ld_text = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")
    updated_by_user_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
