from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.core.auth_realm import AUTH_REALM_CARSCU, AUTH_REALM_NEWCAR_SUPERSTORE, login_realm_allows
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
from app.models.credit_union import CreditUnion, CreditUnionMemberInvite, CuMemberApproval
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

_APPROVAL_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_SIGNUP_NEED_INVITE = (
    "Accounts are created through your credit union. Use the invitation or pre-approval link they sent you."
)
_ORPHAN_MEMBER_LOGIN = (
    "Member accounts must be linked to a credit union. Open the invitation your credit union sent you, or contact them for access."
)


def _signup_tokens_present(data: RegisterRequest) -> bool:
    mit = (data.member_invite_token or "").strip()
    cst = (data.cu_signup_token or "").strip()
    apc = (data.approval_claim_code or "").strip()
    return bool(mit or cst or apc)


def _require_signup_tokens(data: RegisterRequest) -> None:
    if not _signup_tokens_present(data):
        raise HTTPException(status_code=400, detail=_SIGNUP_NEED_INVITE)


def _require_customer_credit_union(user: User) -> None:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val != UserRole.customer.value:
        return
    if user.credit_union_id is None:
        raise HTTPException(status_code=400, detail=_SIGNUP_NEED_INVITE)


def _normalize_phone_digits(raw: str | None) -> str:
    return re.sub(r"\D", "", raw or "")


def _names_match(expected: str | None, got: str | None) -> bool:
    e = " ".join((expected or "").split()).lower()
    if not e:
        return True
    g = " ".join((got or "").split()).lower()
    return e == g


def _phones_match(expected: str | None, got: str | None) -> bool:
    if not (expected or "").strip():
        return True
    return _normalize_phone_digits(expected) == _normalize_phone_digits(got)


def _member_invite_and_cu(
    db: Session,
    token: str,
    registration_email: str,
    registration_name: str,
    registration_phone: str | None,
):
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
    want_name = (inv.invited_name or "").strip()
    if want_name and not _names_match(want_name, registration_name):
        raise HTTPException(
            status_code=400,
            detail="Use the name this invitation was created for.",
        )
    want_phone = (inv.invited_phone or "").strip()
    if want_phone and not _phones_match(want_phone, registration_phone):
        raise HTTPException(
            status_code=400,
            detail="Use the phone number this invitation was created for.",
        )
    return inv, cu


def _validate_approval_for_registration(
    db: Session,
    code: str,
    registration_email: str,
    registration_name: str,
    registration_phone: str | None,
) -> int:
    c = (code or "").strip()
    if not c or len(c) > 64 or not _APPROVAL_CODE_RE.match(c):
        raise HTTPException(status_code=400, detail="Invalid approval reference.")
    row = db.query(CuMemberApproval).filter(CuMemberApproval.approval_code == c).first()
    if not row:
        raise HTTPException(status_code=400, detail="Invalid approval reference.")
    want_em = (row.member_email or "").strip().lower()
    if want_em and want_em != (registration_email or "").strip().lower():
        raise HTTPException(
            status_code=400,
            detail="Use the email address on file for this approval.",
        )
    want_name = (row.member_name or "").strip()
    if want_name and not _names_match(want_name, registration_name):
        raise HTTPException(
            status_code=400,
            detail="Use the name on file for this approval.",
        )
    want_phone = (row.member_phone or "").strip()
    if want_phone and not _phones_match(want_phone, registration_phone):
        raise HTTPException(
            status_code=400,
            detail="Use the phone number on file for this approval.",
        )
    return int(row.credit_union_id)


def _credit_union_id_from_signup_payload(db: Session, data: RegisterRequest) -> int | None:
    mit = (data.member_invite_token or "").strip()
    if mit:
        _, cu = _member_invite_and_cu(db, mit, str(data.email), str(data.name), data.phone)
        return cu.id
    apc = (data.approval_claim_code or "").strip()
    if apc:
        return _validate_approval_for_registration(db, apc, str(data.email), str(data.name), data.phone)
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


def _legacy_null_user_should_be_cu_realm(user: User, requested_realm: str | None) -> bool:
    """
    Allow CU-linked legacy users (auth_realm NULL) to recover login on carscu.com.
    This does NOT broaden cross-site access for general marketplace users.
    """
    return (
        user.auth_realm is None
        and requested_realm == AUTH_REALM_CARSCU
        and (user.credit_union_id is not None or user.role == UserRole.credit_union)
    )


def _register_effective_realm(data: RegisterRequest) -> str:
    """Explicit auth_realm from client, or server default when omitted (avoids 422 for older builds)."""
    return data.auth_realm if data.auth_realm is not None else _legacy_realm()


def _verify_effective_realm(data: RegisterVerifyRequest) -> str:
    return data.auth_realm if data.auth_realm is not None else _legacy_realm()


def _login_effective_realm(data: LoginRequest) -> str:
    return data.auth_realm if data.auth_realm is not None else _legacy_realm()


def _user_by_email_realm(db: Session, email: str, realm: str) -> User | None:
    return (
        db.query(User)
        .filter(User.email == email, User.auth_realm == realm)
        .first()
    )


def _token_subject(user: User) -> str:
    """JWT sub is user id so the same email can exist on multiple auth realms."""
    return str(user.id)


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

    realm = payload.auth_realm if payload.auth_realm is not None else _legacy_realm()
    user = _user_by_email_realm(db, email, realm)
    if not user:
        if realm == AUTH_REALM_CARSCU:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Use the signup link from your credit union to create an account.",
            )
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
        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        if realm == AUTH_REALM_CARSCU and role_val == UserRole.customer.value and user.credit_union_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ORPHAN_MEMBER_LOGIN)
        if email_verified and not user.is_email_verified:
            user.is_email_verified = True
            db.commit()

    sub = _token_subject(user)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    realm = _register_effective_realm(data)
    _require_signup_tokens(data)
    existing = _user_by_email_realm(db, str(data.email), realm)
    if existing:
        if existing.password_hash:
            raise HTTPException(
                status_code=409,
                detail="User already registered for this site. Please log in.",
            )
        # Incomplete signup row for this realm only — replace.
        db.delete(existing)
        db.commit()

    password_hash = hash_password(data.password)

    invite_row = None
    credit_union_id: int | None
    mit = (data.member_invite_token or "").strip()
    if mit:
        invite_row, cu_inv = _member_invite_and_cu(db, mit, str(data.email), str(data.name), data.phone)
        credit_union_id = cu_inv.id
    else:
        credit_union_id = _credit_union_id_from_signup_payload(db, data)
    if credit_union_id is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired credit union invitation. Request a new link from your credit union.",
        )

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

    sub = _token_subject(user)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/register/request-otp")
@router.post("/request-otp")
@router.post("/otp/request")
def request_otp(data: RegisterRequest, db: Session = Depends(get_db)):
    channel = _to_channel(data.channel)
    realm = _register_effective_realm(data)
    _require_signup_tokens(data)

    user = _user_by_email_realm(db, str(data.email), realm)
    if user and _is_registration_complete(user) and user.password_hash:
        raise HTTPException(
            status_code=409,
            detail="User already registered for this site. Please log in.",
        )

    password_hash = hash_password(data.password)
    credit_union_id = _credit_union_id_from_signup_payload(db, data)
    if credit_union_id is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired credit union invitation. Request a new link from your credit union.",
        )
    if user:
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
    realm = _verify_effective_realm(data)
    user = _user_by_email_realm(db, str(data.email), realm)
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
    apc = (data.approval_claim_code or "").strip()
    if mit:
        inv, cu = _member_invite_and_cu(db, mit, str(data.email), user.name, user.phone)
        user.credit_union_id = cu.id
        inv.used_at = datetime.utcnow()
        inv.used_by_user_id = user.id
    elif apc:
        user.credit_union_id = _validate_approval_for_registration(
            db, apc, str(data.email), user.name, user.phone
        )
    elif data.cu_signup_token and data.cu_signup_token.strip():
        cu = db.query(CreditUnion).filter(
            CreditUnion.signup_token == data.cu_signup_token.strip(),
            CreditUnion.is_active == True,
        ).first()
        if cu:
            user.credit_union_id = cu.id
    db.commit()
    db.refresh(user)
    _require_customer_credit_union(user)

    sub = _token_subject(user)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    eff_realm = _login_effective_realm(data)
    candidates = db.query(User).filter(User.email == data.email).all()
    matches: list[User] = []
    for u in candidates:
        if not u.password_hash or not verify_password(data.password, u.password_hash):
            continue
        if login_realm_allows(u.auth_realm, data.auth_realm, _legacy_realm()) or _legacy_null_user_should_be_cu_realm(
            u, data.auth_realm
        ):
            matches.append(u)
    if not matches:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if len(matches) > 1:
        exact = [u for u in matches if (u.auth_realm or "").strip() == eff_realm]
        user = exact[0] if exact else matches[0]
    else:
        user = matches[0]
    if not _is_registration_complete(user):
        raise HTTPException(status_code=403, detail="Complete OTP verification before login")

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if (
        eff_realm == AUTH_REALM_CARSCU
        and role_val == UserRole.customer.value
        and user.credit_union_id is None
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ORPHAN_MEMBER_LOGIN)

    if _legacy_null_user_should_be_cu_realm(user, data.auth_realm):
        # One-time auto-heal: persist realm so future logins are deterministic.
        user.auth_realm = AUTH_REALM_CARSCU
        db.commit()

    sub = _token_subject(user)
    access = create_access_token(sub)
    refresh = create_refresh_token(sub)
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
