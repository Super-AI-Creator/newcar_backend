from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class GoogleAuthRequest(BaseModel):
    id_token: str


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


class RegisterVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    channel: str = Field(default="email", pattern="^(email|sms)$")
    cu_signup_token: Optional[str] = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
