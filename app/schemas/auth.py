from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


AuthRealm = Literal["carscu", "newcar_superstore"]


class GoogleAuthRequest(BaseModel):
    id_token: str
    """Which public site is signing in (isolates accounts vs carscu.com)."""
    auth_realm: Optional[AuthRealm] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class OtpRequest(BaseModel):
    email: EmailStr
    channel: str = "email"


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=50)
    channel: str = Field(default="email", pattern="^(email|sms)$")
    cu_signup_token: Optional[str] = Field(default=None, max_length=128)
    member_invite_token: Optional[str] = Field(
        default=None,
        max_length=128,
        description="One-time personal invite from CU staff; takes precedence over cu_signup_token.",
    )
    auth_realm: AuthRealm


class RegisterVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    channel: str = Field(default="email", pattern="^(email|sms)$")
    cu_signup_token: Optional[str] = Field(default=None, max_length=128)
    member_invite_token: Optional[str] = Field(default=None, max_length=128)
    auth_realm: Optional[AuthRealm] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    auth_realm: Optional[AuthRealm] = None


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
