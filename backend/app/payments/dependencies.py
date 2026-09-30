"""
require_subscription — FastAPI dependency for gating premium content.

Free tier:   SQL problems 1–30 (by created_at order) + daily question set.
Paid tiers:  Full access to all questions across all challenge types.
"""
from typing import Optional

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


# ─── Free daily set ──────────────────────────────────────────────────────────
# Free users get exactly the 3 SQL problems of today's daily set (easy / medium /
# advanced). Python, PySpark and DSA daily problems are paid-plan only, so their
# columns are deliberately NOT listed here.
_TODAY_IST = "((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date"


async def is_free_daily_sql_problem(conn, problem_id: str) -> bool:
    """True if problem_id is one of today's three free SQL daily problems."""
    row = await conn.fetchval(
        f"""
        SELECT 1 FROM core.daily_practice
        WHERE date = {_TODAY_IST}
          AND $1 IN (easy_problem_id, medium_problem_id, advanced_problem_id)
        LIMIT 1
        """,
        problem_id,
    )
    return row is not None


async def problem_needs_paid(conn, problem_id: str) -> Optional[bool]:
    """
    None if the problem does not exist, otherwise whether its content needs a paid plan.
    Same rule as /problems/{id}, /datasets, /expected and /execute: free users get SQL problems
    1 to FREE_TIER_SQL_LIMIT and today's three SQL daily problems; everything else is paid.
    """
    prob = await conn.fetchrow(
        "SELECT challenge_type, row_number FROM core.problems WHERE id = $1",
        problem_id,
    )
    if not prob:
        return None
    challenge_type = prob["challenge_type"]
    raw_row = prob["row_number"]
    if (raw_row is None or raw_row <= 0) and challenge_type == "sql":
        row_num = await conn.fetchval(
            """
            SELECT COUNT(*) FROM core.problems
            WHERE challenge_type = 'sql'
              AND (created_at < (SELECT created_at FROM core.problems WHERE id = $1)
                   OR (created_at = (SELECT created_at FROM core.problems WHERE id = $1) AND id <= $1))
            """,
            problem_id,
        ) or 1
    else:
        row_num = raw_row or 0
    is_non_sql = challenge_type != "sql"
    return (is_non_sql or row_num > FREE_TIER_SQL_LIMIT) and not await is_free_daily_sql_problem(conn, problem_id)


async def get_free_daily_sql_ids(conn) -> set:
    """IDs (as str) of today's three free SQL daily problems."""
    row = await conn.fetchrow(
        f"""
        SELECT easy_problem_id, medium_problem_id, advanced_problem_id
        FROM core.daily_practice
        WHERE date = {_TODAY_IST}
        """
    )
    return {str(v) for v in row.values() if v is not None} if row else set()
