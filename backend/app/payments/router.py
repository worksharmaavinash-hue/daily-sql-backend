"""
Payments router — Full subscription lifecycle via Cashfree PG REST API.

Endpoints:
  POST /api/payments/create-order       → Create Cashfree order & pending subscription
  POST /api/payments/webhook            → Cashfree async notification (activates subscription)
  GET  /api/payments/verify-order/{id}  → Client-side verification after modal close
  GET  /api/payments/my-subscription    → Current user's active plan details
  POST /api/payments/cancel             → Cancel an active subscription
"""
import os
import uuid
import json
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional

from app.auth.jwt import verify_jwt, verify_jwt_optional
from app.db import get_pool
from app.payments.subscription_service import (
    create_pending_subscription,
    activate_subscription,
    get_active_subscription,
    has_active_subscription,
    verify_cashfree_webhook_signature,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ─── Config ──────────────────────────────────────────────────────────────────
CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID", "")
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY", "")
CASHFREE_ENV = os.getenv("CASHFREE_ENV", "sandbox").lower()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

CASHFREE_BASE_URL = (
    "https://sandbox.cashfree.com/pg"
    if CASHFREE_ENV == "sandbox"
    else "https://api.cashfree.com/pg"
)

CASHFREE_HEADERS = {
    "x-client-id": CASHFREE_APP_ID,
    "x-client-secret": CASHFREE_SECRET_KEY,
    "x-api-version": "2025-01-01",
    "Content-Type": "application/json",
}

PLAN_DETAILS = {
    "monthly":  {"name": "Monthly Plan",  "amount": 899.00},
    "yearly":   {"name": "Yearly Plan",   "amount": 1499.00},
    "lifetime": {"name": "Lifetime Plan", "amount": 4999.00},
}


# ─── Pydantic models ─────────────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    plan_id: str


class CancelRequest(BaseModel):
    reason: Optional[str] = None


# ─── 1. Create Order ─────────────────────────────────────────────────────────
@router.post("/create-order")
async def create_order(
    payload: CreateOrderRequest,
    user: dict = Depends(verify_jwt),        # auth required
):
    """
    Creates a Cashfree payment order and a pending subscription record in DB.
    Returns payment_session_id for the frontend to open the checkout modal.
    """
    if payload.plan_id not in PLAN_DETAILS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan_id. Must be one of: {list(PLAN_DETAILS.keys())}",
        )

    plan = PLAN_DETAILS[payload.plan_id]
    order_id = f"dsql_{payload.plan_id}_{uuid.uuid4().hex[:10]}"
    user_id = user["user_id"]
    user_email = user.get("email", "user@dailysql.in")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Fetch user details for Cashfree
        db_user = await conn.fetchrow(
            "SELECT full_name, email FROM core.users WHERE user_id = $1",
            user_id,
        )
        customer_name = (db_user["full_name"] if db_user and db_user["full_name"] else "Daily SQL User")
        customer_email = (db_user["email"] if db_user and db_user["email"] else user_email)

        # Block if already has active subscription (idempotency guard)
        if await has_active_subscription(conn, user_id):
            raise HTTPException(
                status_code=409,
                detail="already_subscribed",
            )

        # Create Cashfree order
        cashfree_payload = {
            "order_id": order_id,
            "order_amount": plan["amount"],
            "order_currency": "INR",
            "customer_details": {
                "customer_id": user_id,
                "customer_email": customer_email,
                "customer_phone": "9999999999",   # user can update later
                "customer_name": customer_name,
            },
            "order_meta": {
                "return_url": f"{FRONTEND_URL}/payment/success?order_id={order_id}",
            },
            "order_note": f"Daily SQL – {plan['name']}",
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{CASHFREE_BASE_URL}/orders",
                    json=cashfree_payload,
                    headers=CASHFREE_HEADERS,
                    timeout=15.0,
                )
                resp.raise_for_status()
                cf_data = resp.json()
            except httpx.HTTPStatusError as exc:
                try:
                    err = exc.response.json()
                except Exception:
                    err = exc.response.text
                raise HTTPException(status_code=exc.response.status_code, detail=err)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Cashfree unavailable: {exc}")

        # Store pending subscription in DB
        await create_pending_subscription(conn, user_id, payload.plan_id, order_id)

    return {
        "success": True,
        "order_id": order_id,
        "payment_session_id": cf_data.get("payment_session_id"),
        "order_amount": plan["amount"],
        "plan_id": payload.plan_id,
        "plan_name": plan["name"],
        "environment": CASHFREE_ENV,
    }


# ─── 2. Cashfree Webhook (server-to-server, async) ────────────────────────────
@router.post("/webhook")
async def cashfree_webhook(request: Request):
    """
    Receives async payment notifications from Cashfree.
    Verifies HMAC-SHA256 signature and activates the subscription on PAYMENT_SUCCESS.
    """
    raw_body = await request.body()

    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")

    # Signature verification is mandatory — reject requests that skip it
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature headers")

    if not CASHFREE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Webhook secret not configured on server")

    if not verify_cashfree_webhook_signature(timestamp, raw_body, signature, CASHFREE_SECRET_KEY):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = body.get("type", "")
    data = body.get("data", {})
    order_data = data.get("order", {})
    payment_data = data.get("payment", {})

    order_id = order_data.get("order_id") or data.get("order_id")
    cf_payment_id = payment_data.get("cf_payment_id") or data.get("cf_payment_id")
    amount_paid = float(payment_data.get("payment_amount") or order_data.get("order_amount") or 0)

    if event_type == "PAYMENT_SUCCESS_WEBHOOK" and order_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await activate_subscription(conn, order_id, str(cf_payment_id), amount_paid)
            if result:
                print(f"[Webhook] Subscription activated: user={result['user_id']} plan={result['plan_id']}")
            else:
                print(f"[Webhook] No pending subscription found for order_id={order_id}")

    # Always return 200 to Cashfree — retry logic is on their side
    return {"status": "ok"}


# ─── 3. Client-side verify (after modal close) ───────────────────────────────
@router.get("/verify-order/{order_id}")
async def verify_order(order_id: str, user: dict = Depends(verify_jwt)):
    """
    Frontend polls this after the Cashfree modal closes to confirm payment status.
    Also activates subscription if Cashfree says PAID but webhook hasn't fired yet.
    """
    # Call Cashfree to get real-time order status
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{CASHFREE_BASE_URL}/orders/{order_id}",
                headers=CASHFREE_HEADERS,
                timeout=15.0,
            )
            resp.raise_for_status()
            cf_order = resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Failed to fetch order from Cashfree")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    order_status = cf_order.get("order_status")  # PAID | ACTIVE | EXPIRED

    pool = await get_pool()
    async with pool.acquire() as conn:
        # SECURITY: Verify this order was created by the requesting user
        owner_row = await conn.fetchrow(
            "SELECT user_id FROM core.subscriptions WHERE cashfree_order_id = $1",
            order_id,
        )
        if not owner_row or str(owner_row["user_id"]) != str(user["user_id"]):
            raise HTTPException(status_code=403, detail="Order not found or does not belong to you")

        # If Cashfree says PAID, activate in DB (idempotent — handles webhook delay)
        if order_status == "PAID":
            # Try to find payment id from Cashfree payments list
            cf_payment_id = cf_order.get("cf_order_id", "unknown")
            try:
                pay_resp = await client.get(
                    f"{CASHFREE_BASE_URL}/orders/{order_id}/payments",
                    headers=CASHFREE_HEADERS,
                    timeout=10.0,
                )
                if pay_resp.status_code == 200:
                    payments = pay_resp.json()
                    if payments:
                        cf_payment_id = str(payments[0].get("cf_payment_id", cf_payment_id))
            except Exception:
                pass

            amount = float(cf_order.get("order_amount", 0))
            await activate_subscription(conn, order_id, cf_payment_id, amount)

        # Return current subscription state
        sub = await get_active_subscription(conn, user["user_id"])

    return {
        "success": True,
        "order_id": order_id,
        "order_status": order_status,
        "subscription": sub,
    }


# ─── 4. My Subscription ──────────────────────────────────────────────────────
@router.get("/my-subscription")
async def my_subscription(user: dict = Depends(verify_jwt)):
    """Returns the logged-in user's active subscription and trial details."""
    pool = await get_pool()
    from app.payments.subscription_service import get_user_full_access_status
    async with pool.acquire() as conn:
        status_info = await get_user_full_access_status(conn, user["user_id"])
        sub = await get_active_subscription(conn, user["user_id"])

    plan = status_info["plan"]
    return {
        **status_info,
        "subscription": sub,
        "plan_details": PLAN_DETAILS.get(plan) if plan != "free" else None,
    }



# ─── 5. Cancel Subscription ──────────────────────────────────────────────────
@router.post("/cancel")
async def cancel_subscription(
    payload: CancelRequest,
    user: dict = Depends(verify_jwt),
):
    """
    Marks the user's active subscription as cancelled.
    Access continues until expires_at — no mid-cycle refund here.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE core.subscriptions
            SET status = 'cancelled', updated_at = NOW()
            WHERE user_id = $1 AND status = 'active'
            """,
            user["user_id"],
        )
        # SECURITY FIX: Only downgrade to free once the plan actually expires.
        # Immediately reset would break the paid user's remaining period.
        # For lifetime users, do nothing (they paid once, forever).
        # For monthly/yearly, just mark cancelled — expiry sweep handles the rest.
        # We do NOT reset plan here; let expire_stale_subscriptions() do it.

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="No active subscription to cancel")

    return {"success": True, "message": "Subscription cancelled successfully."}
