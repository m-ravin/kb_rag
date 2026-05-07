"""
JWT-based authentication for the CMS backend.
Uses role-based access control stored in Cosmos MongoDB.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.core.config import get_settings
from backend.core.clients import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/manage/auth/token")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    s = get_settings()
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes)
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    """Dependency: decodes JWT and returns the user document from MongoDB."""
    s = get_settings()
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
        email: str = payload.get("sub", "")
        if not email:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    db = get_db()
    user = await db["users"].find_one({"email": email})
    if not user:
        raise credentials_exc
    return user


def require_role(*roles: str):
    """Dependency factory: raises 403 if user doesn't have one of the given roles."""
    async def check(user: Annotated[dict, Depends(get_current_user)]):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return check
