import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .config import get_settings
from .db import get_db
from .models import Role, User

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def hash_password(value: str) -> str:
    return _ph.hash(value)

def verify_password(value: str, digest: str) -> bool:
    try:
        return _ph.verify(digest, value)
    except VerifyMismatchError:
        return False

def opaque_token() -> str:
    return secrets.token_urlsafe(48)

def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def create_access_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    ttl = int(settings.access_token_minutes) * 60
    now = utcnow()
    token = jwt.encode(
        {"sub": str(user.id), "role": user.role.value, "type": "access",
         "iat": now, "exp": now + timedelta(seconds=ttl)},
        settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, ttl

def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret.get_secret_value(),
                             algorithms=[settings.jwt_algorithm])
        assert payload.get("type") == "access"
        return UUID(payload["sub"])
    except (jwt.PyJWTError, AssertionError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired access token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc

def current_user(token: Annotated[str, Depends(oauth2_scheme)],
                 db: Annotated[Session, Depends(get_db)]) -> User:
    user = db.get(User, decode_access_token(token))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive or unknown user")
    return user

def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user

CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
