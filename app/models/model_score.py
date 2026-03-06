from sqlalchemy import BigInteger, Column, Integer, String, UniqueConstraint
from app.models.base import Base


class ModelScore(Base):
    __tablename__ = "model_scores"
    __table_args__ = (
        UniqueConstraint("make", "model", "trim", "year", name="uq_model_scores_make_model_trim_year"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    make = Column(String(100), nullable=False, index=True)
    model = Column(String(100), nullable=False, index=True)
    trim = Column(String(100), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)
    design = Column(Integer, nullable=False)
    performance = Column(Integer, nullable=False)
    technology = Column(Integer, nullable=False)
    practicality = Column(Integer, nullable=False)
    future_value = Column(Integer, nullable=False)
