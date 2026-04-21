from typing import Literal, Optional

from pydantic import BaseModel


class FavoriteOut(BaseModel):
    vin: str
    created_at: str


class BrokerMessageIn(BaseModel):
    vin: Optional[str] = None
    message_text: str
    # Where the member message appears: both threads, CU-only, or dealer-only (stored prefix differs).
    audience: Literal["both", "cu", "broker"] = "both"


class BrokerReplyIn(BaseModel):
    customer_user_id: int
    vin: Optional[str] = None
    message_text: str


class CreditApplicationIn(BaseModel):
    payload_json: dict
    vin: Optional[str] = None


class PublicCreditApplicationIn(BaseModel):
    first_name: str
    last_name: str
    email: str
    birth_date: Optional[str] = None
    ssn: Optional[str] = None
    drivers_license_number: Optional[str] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    time_at_current_address: Optional[str] = None
    home_phone: Optional[str] = None
    previous_street_address: Optional[str] = None
    previous_city: Optional[str] = None
    previous_state: Optional[str] = None
    previous_zip_code: Optional[str] = None
    time_at_previous_address: Optional[str] = None
    employment_status: Optional[str] = None
    occupation_title: Optional[str] = None
    employer_name: Optional[str] = None
    work_phone: Optional[str] = None
    time_at_current_job: Optional[str] = None
    work_street_address: Optional[str] = None
    work_city: Optional[str] = None
    work_state: Optional[str] = None
    work_zip_code: Optional[str] = None
    previous_employer: Optional[str] = None
    time_at_previous_employer: Optional[str] = None
    gross_monthly_income: Optional[float] = None
    housing_status: Optional[str] = None
    monthly_housing_payment: Optional[float] = None
    salesperson_name: Optional[str] = None
    electronic_signature: Optional[str] = None
    agreed_to_terms: bool = False
    vin: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_trim: Optional[str] = None
    notes: Optional[str] = None
