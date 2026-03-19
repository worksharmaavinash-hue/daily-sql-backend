import os
import uuid
from typing import Optional

import asyncpg
import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from app.auth.jwt import create_access_token
from app.db import get_pool

router = APIRouter(prefix="/auth", tags=["auth"])

import bcrypt

# ── OAuth state signer (CSRF protection) ─────────────────────────────────────
_state_secret = os.getenv("JWT_SECRET", "fallback-dev-secret")
_signer = URLSafeTimedSerializer(_state_secret)

# ── Google OAuth config ───────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


# ── Request / Response models ─────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Password hashing ──────────────────────────────────────────────────────────
def _hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('utf-8')

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(data: RegisterRequest):
    """Create a new email/password account."""
    if len(data.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    pool = await get_pool()
    user_id = str(uuid.uuid4())
    hashed = _hash_password(data.password)

    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO core.users (user_id, email, hashed_password, auth_provider)
                VALUES ($1, $2, $3, 'email')
                """,
                user_id,
                data.email,
                hashed,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists.",
            )

    token = create_access_token(user_id, data.email)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest):
    """Authenticate with email and password, return JWT."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, hashed_password FROM core.users WHERE email = $1 AND auth_provider = 'email'",
            data.email,
        )

    if not row or not row["hashed_password"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not _verify_password(data.password, row["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(str(row["user_id"]), data.email)
    return TokenResponse(access_token=token)


@router.get("/google")
async def google_login():
    """Redirect the browser to Google's OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    state = _signer.dumps("oauth-state")
    redirect_uri = f"{BACKEND_URL}/auth/google/callback"

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }

    import urllib.parse
    url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Exchange Google auth code for a user profile, upsert user, redirect with JWT."""
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=auth_failed")

    # Verify CSRF state
    try:
        _signer.loads(state, max_age=600)
    except BadSignature:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=invalid_state")

    redirect_uri = f"{BACKEND_URL}/auth/google/callback"

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

        if token_resp.status_code != 200:
            return RedirectResponse(f"{FRONTEND_URL}/login?error=token_exchange_failed")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_resp.status_code != 200:
            return RedirectResponse(f"{FRONTEND_URL}/login?error=userinfo_failed")

        userinfo = userinfo_resp.json()

    google_sub = userinfo.get("sub")
    email = userinfo.get("email")
    full_name = userinfo.get("name")

    if not email or not google_sub:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=missing_profile")

    pool = await get_pool()

    async with pool.acquire() as conn:
        # Check if a user with this email already exists (any provider)
        existing = await conn.fetchrow(
            "SELECT user_id FROM core.users WHERE email = $1",
            email,
        )

        if existing:
            # Link Google to the existing account (email/password user logging in with Google)
            await conn.execute(
                """
                UPDATE core.users
                SET auth_provider = 'google', provider_id = $1
                WHERE email = $2
                """,
                google_sub,
                email,
            )
            user_id = str(existing["user_id"])
        else:
            # New user — create account
            user_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO core.users (user_id, email, auth_provider, provider_id, full_name)
                VALUES ($1, $2, 'google', $3, $4)
                """,
                user_id,
                email,
                google_sub,
                full_name,
            )

    jwt_token = create_access_token(user_id, email)

    # Redirect to frontend callback page with the token as a query param
    # The frontend /auth/callback page will store this in a cookie
    return RedirectResponse(f"{FRONTEND_URL}/auth/callback?token={jwt_token}")
