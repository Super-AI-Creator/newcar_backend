import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db
from app.core.email import EmailDeliveryError, send_email
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_code,
    hash_password,
    verify_code,
    verify_password,
)
from app.models.auth_otp import AuthOtp
from app.models.enums import OtpChannel, UserRole
from app.models.user import User
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    RegisterVerifyRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_channel(channel: str) -> OtpChannel:
    if channel == OtpChannel.email.value:
        return OtpChannel.email
    if channel == OtpChannel.sms.value:
        return OtpChannel.sms
    raise HTTPException(status_code=400, detail="Unsupported OTP channel")


def _is_registration_complete(user: User) -> bool:
    return bool(user.is_email_verified or user.is_phone_verified)


@router.post("/google", response_model=TokenResponse)
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        idinfo = google_id_token.verify_oauth2_token(
            payload.id_token, GoogleRequest(), settings.google_client_id
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token") from exc

    email = idinfo.get("email")
    name = idinfo.get("name") or idinfo.get("given_name") or "Member"
    email_verified = bool(idinfo.get("email_verified"))

    if not email:
        raise HTTPException(status_code=400, detail="Google token missing email")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            name=name,
            role=UserRole.customer,
            is_email_verified=email_verified,
            is_phone_verified=False,
            password_hash=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if email_verified and not user.is_email_verified:
            user.is_email_verified = True
            db.commit()

    access = create_access_token(email)
    refresh = create_refresh_token(email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register/request-otp")
@router.post("/request-otp")
@router.post("/otp/request")
def request_otp(data: RegisterRequest, db: Session = Depends(get_db)):
    channel = _to_channel(data.channel)

    user = db.query(User).filter(User.email == data.email).first()
    if user and _is_registration_complete(user) and user.password_hash:
        raise HTTPException(status_code=409, detail="User already registered. Please log in.")

    password_hash = hash_password(data.password)
    if user:
        user.name = data.name
        user.phone = data.phone
        user.password_hash = password_hash
    else:
        user = User(
            email=data.email,
            phone=data.phone,
            name=data.name,
            password_hash=password_hash,
            role=UserRole.customer,
            is_email_verified=False,
            is_phone_verified=False,
        )
        db.add(user)
    db.commit()
    db.refresh(user)

    if channel == OtpChannel.sms and not user.phone:
        raise HTTPException(status_code=400, detail="Phone is required for SMS OTP")

    code = f"{secrets.randbelow(1000000):06d}"
    otp = AuthOtp(
        user_id=user.id,
        channel=channel,
        code_hash=hash_code(code),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.add(otp)
    db.commit()

    if channel == OtpChannel.email:
        try:
            send_email(
                to_email=data.email,
                subject="Your NewCarSuperstore registration code",
                body=f"Your registration code is {code}. It expires in 10 minutes.",
            )
        except EmailDeliveryError as exc:
            if settings.environment.lower() == "local":
                return {"sent": True, "delivery": "skipped", "dev_code": code}
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OTP email service is unavailable. Please try again later.",
            ) from exc
        return {"sent": True}

    if settings.environment.lower() == "local":
        return {"sent": True, "delivery": "skipped", "dev_code": code}

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="SMS OTP service is unavailable. Please use email OTP.",
    )


@router.post("/register/verify-otp")
@router.post("/verify-otp")
@router.post("/otp/verify")
def verify_otp(data: RegisterVerifyRequest, db: Session = Depends(get_db)):
    channel = _to_channel(data.channel)
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Registration data is incomplete")

    otp = (
        db.query(AuthOtp)
        .filter(
            AuthOtp.user_id == user.id,
            AuthOtp.channel == channel,
            AuthOtp.used_at.is_(None),
            AuthOtp.expires_at > datetime.utcnow(),
        )
        .order_by(AuthOtp.created_at.desc())
        .first()
    )
    if not otp or not verify_code(data.code, otp.code_hash):
        raise HTTPException(status_code=400, detail="Invalid code")

    otp.used_at = datetime.utcnow()
    if channel == OtpChannel.email:
        user.is_email_verified = True
    if channel == OtpChannel.sms:
        user.is_phone_verified = True
    db.commit()

    return {"registered": True, "message": "Registration verified. You can now log in with email and password."}


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not _is_registration_complete(user):
        raise HTTPException(status_code=403, detail="Complete OTP verification before login")

    access = create_access_token(user.email)
    refresh = create_refresh_token(user.email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/signin", response_model=TokenResponse, include_in_schema=False)
def signin_alias(data: LoginRequest, db: Session = Depends(get_db)):
    return login(data, db)
