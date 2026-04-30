from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.user import User


security = HTTPBearer(auto_error=False)


def user_from_access_token_subject(db: Session, sub: Optional[str]) -> Optional[User]:
    """
    Resolve JWT subject to a User row.
    New tokens use numeric user id; legacy tokens used email (unique before composite email+realm).
    """
    if not sub:
        return None
    sub_s = str(sub).strip()
    if sub_s.isdigit():
        return db.query(User).filter(User.id == int(sub_s)).first()
    rows = db.query(User).filter(User.email == sub_s).all()
    if len(rows) == 1:
        return rows[0]
    return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_from_access_token_subject(db, sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: str):
    def _dependency(user: User = Depends(get_current_user)) -> User:
        role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
        if role_value not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dependency
