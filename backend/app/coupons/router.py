"""
Coupons Router — Redemption, validation, and launch trial status.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.auth.jwt import verify_jwt
from app.db import get_pool
from app.payments.subscription_service import (
    redeem_coupon,
    get_launch_config,
    get_user_full_access_status,
)

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


class RedeemCouponRequest(BaseModel):
    code: str


@router.post("/redeem")
async def redeem_user_coupon(
    payload: RedeemCouponRequest,
    user: dict = Depends(verify_jwt),
):
    """
    Redeem a unique lifetime coupon code.
    The coupon must match the authenticated user's email address and not be expired or used.
    """
    if not payload.code or not payload.code.strip():
        raise HTTPException(status_code=400, detail="Coupon code is required.")

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await redeem_coupon(
                conn=conn,
                user_id=user["user_id"],
                user_email=user["email"],
                code=payload.code.strip(),
            )
            return result
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to redeem coupon: {str(exc)}")


@router.get("/check/{code}")
async def check_coupon(code: str, user: dict = Depends(verify_jwt)):
    """Check coupon validity for the current logged-in user."""
    clean_code = code.strip().upper()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT code, email, plan_granted, is_used, expires_at
            FROM core.coupons
            WHERE code = $1
            """,
            clean_code,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Invalid coupon code.")

        clean_email = user["email"].lower().strip()
        matches_email = row["email"].lower().strip() == clean_email

        if not matches_email:
            # Don't expose coupon metadata if it doesn't belong to this user
            return {
                "code": clean_code,
                "plan_granted": None,
                "is_used": None,
                "expires_at": None,
                "matches_user_email": False,
                "is_valid": False,
            }

        return {
            "code": row["code"],
            "plan_granted": row["plan_granted"],
            "is_used": row["is_used"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "matches_user_email": True,
            "is_valid": not row["is_used"],
        }


@router.get("/launch-status")
async def get_public_launch_status():
    """Returns whether the global launch trial is active."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cfg = await get_launch_config(conn)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        is_currently_running = bool(
            cfg.get("is_active")
            and cfg.get("trial_start")
            and cfg.get("trial_end")
            and cfg["trial_start"] <= now <= cfg["trial_end"]
        )

        return {
            "is_active": cfg.get("is_active", False),
            "is_currently_running": is_currently_running,
            "trial_days": cfg.get("trial_days", 30),
            "trial_start": cfg["trial_start"].isoformat() if cfg.get("trial_start") else None,
            "trial_end": cfg["trial_end"].isoformat() if cfg.get("trial_end") else None,
            "new_user_trial_days": cfg.get("new_user_trial_days", 7),
        }
