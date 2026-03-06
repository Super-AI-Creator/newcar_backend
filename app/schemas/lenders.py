from typing import Optional

from pydantic import BaseModel, Field


class LenderRateIn(BaseModel):
    lender_name: str = Field(..., min_length=2, max_length=120)
    credit_tier: str = Field(..., min_length=1, max_length=20)
    vehicle_type: str = Field("all", min_length=1, max_length=20)
    apr: float = Field(..., ge=0.0, le=100.0)
    max_term_months: int = Field(..., ge=12, le=120)


class LenderRateOut(BaseModel):
    id: int
    lender_name: str
    credit_tier: str
    vehicle_type: str
    apr: float
    max_term_months: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
