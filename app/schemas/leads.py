from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LeadCreateIn(BaseModel):
    vin: Optional[str] = Field(default=None, max_length=17)
    year: Optional[int] = None
    make: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=120)
    trim: Optional[str] = Field(default=None, max_length=160)
    vehicle: Optional[str] = Field(default=None, max_length=255)
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=60)
    notes: Optional[str] = Field(default=None, max_length=4000)
    source: Optional[str] = Field(default=None, max_length=120)


class LeadCreateOut(BaseModel):
    saved: bool
    lead_id: int
    deal_id: Optional[int] = None
