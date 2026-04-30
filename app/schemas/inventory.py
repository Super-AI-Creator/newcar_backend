from pydantic import BaseModel
from typing import Any, List, Optional

try:
    from pydantic import ConfigDict
except Exception:
    ConfigDict = None


class OfferOverrideOut(BaseModel):
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    discounted_price: Optional[float] = None
    term_months: Optional[int] = None
    miles_per_year: Optional[int] = None


class ModelScoreOut(BaseModel):
    design: int
    performance: int
    technology: int
    practicality: int
    future_value: int


class InventoryItem(BaseModel):
    vin: str
    vehicle_type: Optional[str] = None
    year: Optional[int]
    make: Optional[str]
    model: Optional[str]
    trim: Optional[str]
    msrp: Optional[float]
    estimated_monthly: Optional[float] = None
    listed_price: Optional[float] = None
    mileage: Optional[int] = None
    condition: Optional[str] = None
    details: Optional[dict]
    photos: List[str]
    last_seen_at: Optional[str]
    dealer_name: Optional[str] = None
    dealer_phone: Optional[str] = None
    listing_url: Optional[str] = None
    carfax_url: Optional[str] = None
    offer: Optional[OfferOverrideOut]
    model_scores: Optional[ModelScoreOut]

    if ConfigDict is not None:
        model_config = ConfigDict(protected_namespaces=())


class InventorySearchResponse(BaseModel):
    items: List[InventoryItem]
    page: int
    page_size: int
    total: int
