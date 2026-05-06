from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


AuthRealm = Literal["carscu", "newcar_superstore"]


def _coerce_auth_realm_optional(v):
    """Strip / lowercase / common aliases so clients do not get 422 on minor spelling differences."""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip().lower()
    if not s:
        return None
    if s in ("carscu", "newcar_superstore"):
        return s
    if s in ("newcarsuperstore", "newcar-superstore"):
        return "newcar_superstore"
    return v


class GoogleAuthRequest(BaseModel):
    id_token: str
    """Which public site is signing in (isolates accounts vs carscu.com)."""
    auth_realm: Optional[AuthRealm] = None

    @field_validator("auth_realm", mode="before")
    @classmethod
    def _blank_google_realm(cls, v):
        return _coerce_auth_realm_optional(v)


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
    approval_claim_code: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Pre-approval reference from CU; ties signup to that approval when no invite token.",
    )
    # Omit only for legacy clients; server uses AUTH_REALM_LEGACY_DEFAULT (see settings).
    auth_realm: Optional[AuthRealm] = None

    @field_validator("auth_realm", mode="before")
    @classmethod
    def _blank_auth_realm_to_none(cls, v):
        return _coerce_auth_realm_optional(v)


class RegisterVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    channel: str = Field(default="email", pattern="^(email|sms)$")
    cu_signup_token: Optional[str] = Field(default=None, max_length=128)
    member_invite_token: Optional[str] = Field(default=None, max_length=128)
    approval_claim_code: Optional[str] = Field(default=None, max_length=64)
    auth_realm: Optional[AuthRealm] = None

    @field_validator("auth_realm", mode="before")
    @classmethod
    def _blank_verify_realm(cls, v):
        return _coerce_auth_realm_optional(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    auth_realm: Optional[AuthRealm] = None

    @field_validator("auth_realm", mode="before")
    @classmethod
    def _blank_login_realm(cls, v):
        return _coerce_auth_realm_optional(v)


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
