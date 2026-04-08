from sqlalchemy import BigInteger, Boolean, Column, DateTime, func

from app.models.base import Base


class DealerDashboardSetting(Base):
    """Per legacy dealer_sources.id: whether a dedicated dealer dashboard is active."""

    __tablename__ = "dealer_dashboard_settings"

    dealer_source_id = Column(BigInteger, primary_key=True, autoincrement=False)
    dashboard_activated = Column(Boolean, nullable=False, server_default="0")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
