"""
require_subscription — FastAPI dependency for gating premium content.

Free tier:   SQL problems 1–30 (by created_at order) + daily question set.
Paid tiers:  Full access to all questions across all challenge types.
"""
from fastapi import Depends, HTTPException
from app.auth.jwt import verify_jwt
from app.db import get_pool
from app.payments.subscription_service import has_active_subscription


async def require_subscription(user: dict = Depends(verify_jwt)):
    """
    Dependency that blocks access unless the user has an active paid subscription.
    Returns the user dict on success.
    Raises HTTP 403 with 'subscription_required' detail on failure.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await has_active_subscription(conn, user["user_id"]):
            raise HTTPException(
                status_code=403,
                detail="subscription_required",
            )
    return user


async def get_user_plan(user: dict = Depends(verify_jwt)) -> dict:
    """
    Dependency that attaches the user's plan info to the request context.
    Used on routes that behave differently based on plan (e.g. /problems list).
    Returns: { ...user, plan: 'free'|'monthly'|'yearly'|'lifetime', is_paid: bool }
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT plan, plan_expires_at FROM core.users WHERE user_id = $1",
            user["user_id"],
        )
    from datetime import datetime, timezone
    if not row:
        return {**user, "plan": "free", "is_paid": False}

    plan = row["plan"] or "free"
    expires = row["plan_expires_at"]

    is_paid = (
        plan == "lifetime"
        or (plan in ("monthly", "yearly") and expires is not None and expires > datetime.now(timezone.utc))
    )

    return {**user, "plan": plan, "plan_expires_at": expires, "is_paid": is_paid}


# ─── Free tier problem number boundary ───────────────────────────────────────
FREE_TIER_SQL_LIMIT = 30  # First N SQL problems (by created_at order) are free
