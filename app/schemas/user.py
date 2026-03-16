from pydantic import BaseModel, EmailStr
from typing import Optional

try:
    from pydantic import ConfigDict
except Exception:
    ConfigDict = None


class UserOut(BaseModel):
    id: int
    email: EmailStr
    phone: Optional[str]
    name: str
    role: str
    credit_union_id: Optional[int] = None
    is_phone_verified: bool
    is_email_verified: bool

    if ConfigDict is not None:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            orm_mode = True
