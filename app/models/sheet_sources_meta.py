from sqlalchemy import BigInteger, Column, DateTime, String, Text, func
from app.models.base import Base


class SheetSourceMeta(Base):
    __tablename__ = "sheet_sources_meta"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sheet_name = Column(String(255), nullable=False)
    sheet_id = Column(String(255), nullable=False)
    tab_name = Column(String(255), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    last_row_hash = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
