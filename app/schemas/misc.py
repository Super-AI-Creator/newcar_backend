from typing import Literal, Optional

from pydantic import BaseModel, field_validator


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
    ssn: str
    drivers_license_number: Optional[str] = None
    street_address: str
    city: str
    state: str
    zip_code: str
    time_at_current_address: str
    home_phone: Optional[str] = None
    previous_street_address: Optional[str] = None
    previous_city: Optional[str] = None
    previous_state: Optional[str] = None
    previous_zip_code: Optional[str] = None
    time_at_previous_address: Optional[str] = None
    employment_status: str
    occupation_title: Optional[str] = None
    employer_name: str
    work_phone: str
    time_at_current_job: str
    work_street_address: Optional[str] = None
    work_city: Optional[str] = None
    work_state: Optional[str] = None
    work_zip_code: Optional[str] = None
    previous_employer: Optional[str] = None
    time_at_previous_employer: Optional[str] = None
    gross_monthly_income: float
    housing_status: str
    monthly_housing_payment: float
    salesperson_name: str
    electronic_signature: str
    agreed_to_terms: bool = False
    vin: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_trim: Optional[str] = None
    notes: Optional[str] = None

    @field_validator(
        "first_name",
        "last_name",
        "email",
        "ssn",
        "street_address",
        "city",
        "state",
        "zip_code",
        "time_at_current_address",
        "employment_status",
        "employer_name",
        "work_phone",
        "time_at_current_job",
        "housing_status",
        "salesperson_name",
        "electronic_signature",
        mode="before",
    )
    @classmethod
    def require_non_empty_text(cls, value):
        if value is None or not str(value).strip():
            raise ValueError("This field is required")
        return str(value).strip()

    @field_validator("gross_monthly_income", "monthly_housing_payment", mode="before")
    @classmethod
    def require_non_negative_number(cls, value):
        if value is None or value == "":
            raise ValueError("This field is required")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a valid number") from exc
        if parsed < 0:
            raise ValueError("Amount must be zero or greater")
        return parsed
