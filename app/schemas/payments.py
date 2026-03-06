from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PaymentEstimateResponse(BaseModel):
    vin: str
    vehicle_type: Optional[str] = None
    apr: float
    term: int
    down: float
    vehicle_price: float
    estimated_monthly: float
    primary_offer_monthly: Optional[float] = None
    credit_tier: Optional[str] = None
