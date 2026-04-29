import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.core.auth_realm import login_realm_allows
from app.core.config import settings
from app.core.deps import get_db, get_current_user
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
from app.models.credit_union import CreditUnion, CreditUnionMemberInvite
from app.models.user import User
from app.schemas.user import UserOut
from app.services.user_out import build_user_out
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    RegisterVerifyRequest,
    TokenResponse,
    ProfileUpdateRequest,
    PasswordChangeRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _member_invite_and_cu(db: Session, token: str, registration_email: str):
    """Validate an unused member invite; return (invite_row, credit_union). Raises HTTPException if invalid."""
    inv = (
        db.query(CreditUnionMemberInvite)
        .filter(
            CreditUnionMemberInvite.token == token,
            CreditUnionMemberInvite.used_at.is_(None),
        )
        .first()
    )
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or already used invitation link.")
    cu = (
        db.query(CreditUnion)
        .filter(CreditUnion.id == inv.credit_union_id, CreditUnion.is_active == True)
        .first()
    )
    if not cu:
        raise HTTPException(status_code=400, detail="This invitation is no longer valid.")
    want = (inv.invited_email or "").strip().lower()
    if want and want != (registration_email or "").strip().lower():
        raise HTTPException(
            status_code=400,
            detail="Use the email address this invitation was created for.",
        )
    return inv, cu


def _credit_union_id_from_signup_payload(db: Session, data: RegisterRequest) -> int | None:
    mit = (data.member_invite_token or "").strip()
    if mit:
        _, cu = _member_invite_and_cu(db, mit, str(data.email))
        return cu.id
    if data.cu_signup_token and data.cu_signup_token.strip():
        cu = (
            db.query(CreditUnion)
            .filter(
                CreditUnion.signup_token == data.cu_signup_token.strip(),
                CreditUnion.is_active == True,
            )
            .first()
        )
        return cu.id if cu else None
    return None


def _to_channel(channel: str) -> OtpChannel:
    if channel == OtpChannel.email.value:
        return OtpChannel.email
    if channel == OtpChannel.sms.value:
        return OtpChannel.sms
    raise HTTPException(status_code=400, detail="Unsupported OTP channel")


def _is_registration_complete(user: User) -> bool:
    return bool(user.is_email_verified or user.is_phone_verified)


def _legacy_realm() -> str:
    return (settings.auth_realm_legacy_default or "newcar_superstore").strip()


def _register_effective_realm(data: RegisterRequest) -> str:
    """Explicit auth_realm from client, or server default when omitted (avoids 422 for older builds)."""
    return data.auth_realm if data.auth_realm is not None else _legacy_realm()


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
        realm = payload.auth_realm if payload.auth_realm is not None else _legacy_realm()
        user = User(
            email=email,
            name=name,
            role=UserRole.customer,
            is_email_verified=email_verified,
            is_phone_verified=False,
            password_hash=None,
            auth_realm=realm,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not login_realm_allows(user.auth_realm, payload.auth_realm, _legacy_realm()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")
        if email_verified and not user.is_email_verified:
            user.is_email_verified = True
            db.commit()

    access = create_access_token(email)
    refresh = create_refresh_token(email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        if existing.password_hash:
            raise HTTPException(
                status_code=409,
                detail="User already registered. Please log in.",
            )
        # If a user exists without a password hash, treat as incomplete legacy record.
        db.delete(existing)
        db.commit()

    password_hash = hash_password(data.password)

    invite_row = None
    mit = (data.member_invite_token or "").strip()
    if mit:
        invite_row, cu_inv = _member_invite_and_cu(db, mit, str(data.email))
        credit_union_id = cu_inv.id
    else:
        credit_union_id = _credit_union_id_from_signup_payload(db, data)

    realm = _register_effective_realm(data)
    user = User(
        email=data.email,
        phone=data.phone,
        name=data.name,
        password_hash=password_hash,
        role=UserRole.customer,
        credit_union_id=credit_union_id,
        auth_realm=realm,
        is_email_verified=True,
        is_phone_verified=bool(data.phone),
    )
    db.add(user)
    db.flush()
    if invite_row:
        invite_row.used_at = datetime.utcnow()
        invite_row.used_by_user_id = user.id
    db.commit()
    db.refresh(user)

    access = create_access_token(user.email)
    refresh = create_refresh_token(user.email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register/request-otp")
@router.post("/request-otp")
@router.post("/otp/request")
def request_otp(data: RegisterRequest, db: Session = Depends(get_db)):
    channel = _to_channel(data.channel)
    realm = _register_effective_realm(data)

    user = db.query(User).filter(User.email == data.email).first()
    if user and _is_registration_complete(user) and user.password_hash:
        raise HTTPException(status_code=409, detail="User already registered. Please log in.")

    password_hash = hash_password(data.password)
    credit_union_id = _credit_union_id_from_signup_payload(db, data)
    if user:
        if user.auth_realm and user.auth_realm != realm:
            raise HTTPException(
                status_code=409,
                detail="Continue registration on the site where you started, or use a different email address.",
            )
        user.name = data.name
        user.phone = data.phone
        user.password_hash = password_hash
        user.auth_realm = realm
        if credit_union_id is not None:
            user.credit_union_id = credit_union_id
    else:
        user = User(
            email=data.email,
            phone=data.phone,
            name=data.name,
            password_hash=password_hash,
            role=UserRole.customer,
            credit_union_id=credit_union_id,
            auth_realm=realm,
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


@router.post("/register/verify-otp", response_model=TokenResponse)
@router.post("/verify-otp", response_model=TokenResponse)
@router.post("/otp/verify", response_model=TokenResponse)
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

    if not login_realm_allows(user.auth_realm, data.auth_realm, _legacy_realm()):
        raise HTTPException(
            status_code=400,
            detail="Complete verification on the same website where you requested the code.",
        )

    otp.used_at = datetime.utcnow()
    if channel == OtpChannel.email:
        user.is_email_verified = True
    if channel == OtpChannel.sms:
        user.is_phone_verified = True
    mit = (data.member_invite_token or "").strip()
    if mit:
        inv, cu = _member_invite_and_cu(db, mit, str(data.email))
        user.credit_union_id = cu.id
        inv.used_at = datetime.utcnow()
        inv.used_by_user_id = user.id
    elif data.cu_signup_token and data.cu_signup_token.strip():
        cu = db.query(CreditUnion).filter(
            CreditUnion.signup_token == data.cu_signup_token.strip(),
            CreditUnion.is_active == True,
        ).first()
        if cu:
            user.credit_union_id = cu.id
    db.commit()

    access = create_access_token(user.email)
    refresh = create_refresh_token(user.email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not _is_registration_complete(user):
        raise HTTPException(status_code=403, detail="Complete OTP verification before login")

    if not login_realm_allows(user.auth_realm, data.auth_realm, _legacy_realm()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access = create_access_token(user.email)
    refresh = create_refresh_token(user.email)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/signin", response_model=TokenResponse, include_in_schema=False)
def signin_alias(data: LoginRequest, db: Session = Depends(get_db)):
    return login(data, db)


@router.patch("/me/profile", response_model=UserOut)
def update_profile(payload: ProfileUpdateRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(User).filter(User.id == user.id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    row.name = payload.name
    row.phone = payload.phone
    db.commit()
    db.refresh(row)
    return build_user_out(db, row)


@router.post("/me/change-password")
def change_password(payload: PasswordChangeRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(User).filter(User.id == user.id).first()
    if not row or not row.password_hash:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password login not available for this account")
    if not verify_password(payload.current_password, row.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    row.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"changed": True}
