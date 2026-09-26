import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def create_access_token(user_id: str, email: str, is_admin: bool = False) -> str:
    """Create a signed JWT for a user, optionally with admin privileges."""
    payload = {
        "sub": user_id,
        "email": email,
        "admin": is_admin,
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
        "is_admin": payload.get("admin", False)
    }


def verify_jwt_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional),
) -> Optional[dict]:
    if credentials is None:
        return None
    try:
        payload = _decode_token(credentials.credentials)
        return {
            "user_id": payload["sub"],
            "email": payload.get("email"),
            "is_admin": payload.get("admin", False)
        }
    except HTTPException:
        return None


def create_staff_token(
    staff_id: str,
    email: str,
    full_name: str,
    role: str,
    expiry_hours: int = 24
) -> str:
    """Create a signed JWT specifically for staff (CMS) access."""
    payload = {
        "sub": str(staff_id),
        "email": email,
        "full_name": full_name,
        "role": role,
        "token_type": "staff",
        "admin": role in ("admin", "superadmin"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_admin_jwt(user=Depends(verify_jwt)) -> dict:
    """Dependency for strictly admin-only routes."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin permissions required")
    return user


def require_staff_role(allowed_roles: list[str]):
    """
    Dependency factory that strictly validates staff tokens and verifies required roles.
    Supported roles: 'writer', 'admin', 'superadmin'.
    Also supports legacy X-Admin-Secret header during migration if needed.
    """
    async def role_checker(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional),
    ) -> dict:
        # Check Authorization: Bearer <token>
        if credentials and credentials.credentials:
            try:
                payload = _decode_token(credentials.credentials)
                
                # Check for staff token
                if payload.get("token_type") == "staff":
                    role = payload.get("role")
                    if role in allowed_roles:
                        return {
                            "staff_id": payload["sub"],
                            "email": payload.get("email"),
                            "full_name": payload.get("full_name"),
                            "role": role,
                            "is_admin": role in ("admin", "superadmin"),
                        }
                    raise HTTPException(
                        status_code=403,
                        detail=f"Access denied. Requires one of roles: {', '.join(allowed_roles)}"
                    )
                
                # Legacy consumer token with is_admin flag (treated as admin)
                if payload.get("admin") is True and "admin" in allowed_roles:
                    return {
                        "staff_id": payload["sub"],
                        "email": payload.get("email"),
                        "full_name": "Admin User",
                        "role": "admin",
                        "is_admin": True,
                    }
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

        raise HTTPException(status_code=403, detail="Staff authentication required")

    return role_checker


# Convenient pre-configured role dependencies
require_writer_or_admin = require_staff_role(["writer", "admin", "superadmin"])
require_admin_only = require_staff_role(["admin", "superadmin"])


