from typing import Optional

from pydantic import BaseModel, Field


class DealCreateIn(BaseModel):
    vin: str = Field(..., min_length=5, max_length=17)
    customer_note: Optional[str] = Field(default=None, max_length=4000)


class DealUpdateIn(BaseModel):
    status: Optional[str] = None
    broker_note: Optional[str] = Field(default=None, max_length=4000)
    assigned_broker_user_id: Optional[int] = None
    assigned_broker_email: Optional[str] = Field(default=None, max_length=255)
    delivery_scheduled_at: Optional[str] = None
    delivery_address: Optional[str] = Field(default=None, max_length=255)
    delivery_city: Optional[str] = Field(default=None, max_length=120)
    delivery_state: Optional[str] = Field(default=None, max_length=120)
    delivery_zip: Optional[str] = Field(default=None, max_length=30)
    delivery_notes: Optional[str] = Field(default=None, max_length=4000)


class DealOut(BaseModel):
    id: int
    user_id: int
    vin: str
    status: str
    customer_note: Optional[str] = None
    broker_note: Optional[str] = None
    assigned_broker_user_id: Optional[int] = None
    delivery_scheduled_at: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_state: Optional[str] = None
    delivery_zip: Optional[str] = None
    delivery_notes: Optional[str] = None
    locked_at: Optional[str] = None
    delivered_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    credit_union_id: Optional[int] = None
    credit_union_name: Optional[str] = None
    approval_amount: Optional[float] = None


class DealEventOut(BaseModel):
    id: int
    deal_id: int
    actor_user_id: Optional[int] = None
    event_type: str
    message: Optional[str] = None
    created_at: Optional[str] = None
