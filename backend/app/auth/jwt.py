import jwt
import os
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)
JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

def verify_jwt(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {
        "user_id": payload["sub"],
        "email": payload.get("email")
    }


def verify_jwt_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional)
) -> Optional[dict]:
    """
    Optional JWT verification - returns None for guests, user dict for logged-in users.
    Use this for endpoints that should work for both guests and authenticated users.
    """
    if credentials is None:
        return None
    
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        return {
            "user_id": payload["sub"],
            "email": payload.get("email")
        }
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        # Token is invalid or expired - treat as guest
        return None
