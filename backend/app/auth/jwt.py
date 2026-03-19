import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def create_access_token(user_id: str, email: str) -> str:
    """Create a signed JWT for a user."""
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT, raising HTTPException on failure."""
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT_SECRET not configured")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")


def verify_jwt(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """Required auth — raises 401 if token is missing or invalid."""
    payload = _decode_token(credentials.credentials)
    return {
        "user_id": payload["sub"],
        "email": payload.get("email"),
    }


def verify_jwt_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional),
) -> Optional[dict]:
    """
    Optional auth — returns None for guests, user dict for logged-in users.
    Use this for endpoints that should work for both guests and authenticated users.
    """
    if credentials is None:
        return None
    try:
        payload = _decode_token(credentials.credentials)
        return {
            "user_id": payload["sub"],
            "email": payload.get("email"),
        }
    except HTTPException:
        return None
