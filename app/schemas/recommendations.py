from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class RecommendationExplanation(BaseModel):
    design: float = 0.0
    performance: float = 0.0
    technology: float = 0.0
    practicality: float = 0.0
    future_value: float = 0.0
    preference: Optional[float] = None
    payment_fit: Optional[float] = None
    deal_score: Optional[float] = None
    price_fit: Optional[float] = None
    mileage_score: Optional[float] = None
    condition_score: Optional[float] = None
    freshness: Optional[float] = None
    total: float


class RecommendationItem(BaseModel):
    vin: str
    vehicle_type: Optional[str] = None
    make: Optional[str]
    model: Optional[str]
    trim: Optional[str]
    photo: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    score: float
    explanation: RecommendationExplanation


class RecommendationResponse(BaseModel):
    items: List[RecommendationItem]
