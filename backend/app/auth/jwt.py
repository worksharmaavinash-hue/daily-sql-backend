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
        # Supabase newer projects use ES256 (ECC), older ones use HS256. 
        # We allow both but HS256 is the usual default for "Secrets".
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256", "ES256"],
            audience="authenticated"
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        print(f"JWT Verification Failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

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
            algorithms=["HS256", "ES256"],
            audience="authenticated"
        )
        return {
            "user_id": payload["sub"],
            "email": payload.get("email")
        }
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        # Token is invalid or expired - treat as guest
        if token:
            print(f"Optional JWT Verification Failed: {str(e)}")
        return None
