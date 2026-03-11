import jwt
import os
import json
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)
JWT_SECRET_RAW = os.getenv("SUPABASE_JWT_SECRET")

def get_verification_key():
    """Smart key loader: handles HS256 secrets, PEM strings, or JWK JSON."""
    if not JWT_SECRET_RAW:
        return None
    
    # Check if it's a JWK JSON
    if JWT_SECRET_RAW.strip().startswith('{'):
        try:
            jwk_data = json.loads(JWT_SECRET_RAW)
            from jwt.algorithms import get_default_algorithms
            algo = get_default_algorithms().get('ES256')
            if not algo:
                # If cryptography is missing, this might return None or a dummy
                print("ES256 algorithm not registered. Ensure 'cryptography' is installed.")
                return JWT_SECRET_RAW
            return algo.from_jwk(jwk_data)
        except Exception as e:
            print(f"Failed to parse JWK JSON: {e}")
            return JWT_SECRET_RAW
            
    return JWT_SECRET_RAW

JWT_KEY = get_verification_key()

def verify_jwt(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    token = credentials.credentials
    
    try:
        # Supabase newer projects use ES256 (ECC), older ones use HS256. 
        # We allow both but HS256 is the usual default for "Secrets".
        payload = jwt.decode(
            token,
            JWT_KEY,
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
            JWT_KEY,
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
