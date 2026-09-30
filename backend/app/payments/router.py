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
import re
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
    PLAN_PRICES,
    create_pending_subscription,
    activate_subscription,
    get_active_subscription,
    get_purchase_block,
    revoke_subscription,
    verify_cashfree_webhook_signature,
)
from app.metrics import (
    CHECKOUT_INITIATED,
    PAYMENT_SUCCESS,
    CASHFREE_WEBHOOK_STATUS,
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
    "monthly":  {"name": "Monthly Plan",  "amount": PLAN_PRICES["monthly"]},
    "yearly":   {"name": "Yearly Plan",   "amount": PLAN_PRICES["yearly"]},
    "lifetime": {"name": "Lifetime Plan", "amount": PLAN_PRICES["lifetime"]},
}

# Orders created by create_order() look like dsql_<plan>_<10 hex chars>. Anything else (coupon / manual-grant
# reference numbers, or attacker-supplied text) is never sent to Cashfree.
ORDER_ID_RE = re.compile(r"^dsql_(monthly|yearly|lifetime)_[0-9a-f]{10}$")


def _extract_order_id(data: dict) -> Optional[str]:
    """Cashfree puts the order id in different places depending on the event type."""
    for path in (
        ("order", "order_id"),
        ("order_id",),
        ("refund", "order_id"),
        ("dispute", "order_id"),
        ("order_details", "order_id"),
    ):
        cur = data
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if isinstance(cur, str) and cur:
            return cur
    return None


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
            "SELECT full_name, email, whatsapp_number FROM core.users WHERE user_id = $1",
            user_id,
        )
        customer_name = (db_user["full_name"] if db_user and db_user["full_name"] else "Daily SQL User")
        customer_email = (db_user["email"] if db_user and db_user["email"] else user_email)

        # Cashfree requires customer_phone on every order. Use the real number when the user gave
        # one during onboarding (keep only the last 10 digits, so "+91 99999 99999" or "91999..."
        # both normalise the same way); fall back to a placeholder otherwise — Cashfree's checkout
        # lets the customer correct it inline, so this never blocks a real payment either way.
        raw_phone = (db_user["whatsapp_number"] if db_user else None) or ""
        digits = "".join(c for c in raw_phone if c.isdigit())
        customer_phone = digits[-10:] if len(digits) >= 10 else "9999999999"

        # Trial users may buy, the same plan renews and a higher plan upgrades. Only a Lifetime holder,
        # or buying a plan lower than the one already held, is refused.
        block = await get_purchase_block(conn, user_id, payload.plan_id)
        if block:
            raise HTTPException(status_code=409, detail=block)

        # Create Cashfree order
        cashfree_payload = {
            "order_id": order_id,
            "order_amount": plan["amount"],
            "order_currency": "INR",
            "customer_details": {
                "customer_id": user_id,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
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
                # Our own credentials/config problems must not look like the user's login failing
                if exc.response.status_code in (401, 403):
                    print(f"[Payments] Cashfree rejected our credentials: {err}")
                    raise HTTPException(status_code=502, detail="Payment provider is temporarily unavailable.")
                raise HTTPException(status_code=exc.response.status_code, detail=err)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Cashfree unavailable: {exc}")

        # Store pending subscription in DB
        await create_pending_subscription(conn, user_id, payload.plan_id, order_id)
        CHECKOUT_INITIATED.labels(plan_id=payload.plan_id).inc()

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
    Verifies the HMAC-SHA256 signature, then:
      - PAYMENT_SUCCESS_WEBHOOK  → activates the plan (idempotent, exactly once)
      - REFUND_STATUS_WEBHOOK    → a fully refunded order loses its access
      - DISPUTE_CREATED          → a chargeback suspends the access it gave
    Everything else is acknowledged and ignored.
    """
    raw_body = await request.body()

    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")

    # Signature verification is mandatory — reject requests that skip it
    if not timestamp or not signature:
        CASHFREE_WEBHOOK_STATUS.labels(event_type="signature_verification", status="missing_headers").inc()
        raise HTTPException(status_code=401, detail="Missing webhook signature headers")

    if not CASHFREE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Webhook secret not configured on server")

    if not verify_cashfree_webhook_signature(timestamp, raw_body, signature, CASHFREE_SECRET_KEY):
        CASHFREE_WEBHOOK_STATUS.labels(event_type="signature_verification", status="signature_error").inc()
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        CASHFREE_WEBHOOK_STATUS.labels(event_type="json_decode", status="invalid_json").inc()
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = body.get("type", "")
    data = body.get("data") or {}
    order_id = _extract_order_id(data)

    if not order_id:
        CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type or "other", status="ignored").inc()
        return {"status": "ok"}

    pool = await get_pool()

    if event_type == "PAYMENT_SUCCESS_WEBHOOK":
        order_data = data.get("order") or {}
        payment_data = data.get("payment") or {}
        cf_payment_id = payment_data.get("cf_payment_id") or data.get("cf_payment_id")
        amount_paid = float(payment_data.get("payment_amount") or order_data.get("order_amount") or 0)
        order_amount = order_data.get("order_amount")
        async with pool.acquire() as conn:
            result = await activate_subscription(
                conn, order_id, str(cf_payment_id), amount_paid,
                order_amount=float(order_amount) if order_amount is not None else None,
            )
        if result is None:
            CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status="order_not_found").inc()
            print(f"[Webhook] No pending subscription found for order_id={order_id}")
        elif result.get("activated"):
            CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status="success").inc()
            PAYMENT_SUCCESS.labels(plan_id=result.get("plan_id", "unknown")).inc()
            print(f"[Webhook] Subscription activated: user={result['user_id']} plan={result['plan_id']}")
        else:
            reason = result.get("reason", "ignored")
            CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status=reason).inc()
            if reason == "amount_mismatch":
                print(f"[Webhook] REFUSED to activate {order_id}: order amount does not match the plan price")

    elif event_type == "REFUND_STATUS_WEBHOOK":
        refund = data.get("refund") or {}
        if str(refund.get("refund_status", "")).upper() == "SUCCESS":
            refunded = float(refund.get("refund_amount") or 0)
            async with pool.acquire() as conn:
                sub = await conn.fetchrow(
                    "SELECT plan_id, amount_paid FROM core.subscriptions WHERE cashfree_order_id = $1",
                    order_id,
                )
                paid = float(sub["amount_paid"] or 0) if sub else 0.0
                if sub and paid <= 0:
                    paid = PLAN_PRICES.get(sub["plan_id"], 0.0)
                if sub and refunded >= paid - 0.01:
                    revoked = await revoke_subscription(
                        conn, order_id, "refunded", reason="Full refund via Cashfree", refunded_amount=refunded,
                    )
                    status = "revoked" if revoked else "nothing_to_revoke"
                    print(f"[Webhook] Refund {status}: order={order_id} amount={refunded}")
                elif sub:
                    await conn.execute(
                        "UPDATE core.subscriptions SET refunded_amount = GREATEST(COALESCE(refunded_amount, 0), $2), "
                        "updated_at = NOW() WHERE cashfree_order_id = $1",
                        order_id, refunded,
                    )
                    status = "partial_recorded"
                    print(f"[Webhook] Partial refund recorded (access kept): order={order_id} amount={refunded}")
                else:
                    status = "order_not_found"
            CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status=status).inc()
        else:
            CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status="not_final").inc()

    elif event_type == "DISPUTE_CREATED":
        async with pool.acquire() as conn:
            revoked = await revoke_subscription(conn, order_id, "disputed", reason="Chargeback / dispute opened")
        CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type, status="revoked" if revoked else "nothing_to_revoke").inc()
        print(f"[Webhook] Dispute opened: order={order_id} access {'suspended' if revoked else 'unchanged'}")

    else:
        CASHFREE_WEBHOOK_STATUS.labels(event_type=event_type or "other", status="ignored").inc()

    # Always return 200 to Cashfree — retry logic is on their side
    return {"status": "ok"}


# ─── 3. Client-side verify (after modal close) ───────────────────────────────
@router.get("/verify-order/{order_id}")
async def verify_order(order_id: str, user: dict = Depends(verify_jwt)):
    """
    Frontend polls this after the Cashfree modal closes to confirm payment status.
    Also activates the plan if Cashfree says PAID but the webhook has not arrived yet.
    Safe to call any number of times: activation happens at most once per order, and a cancelled,
    expired, refunded or revoked order is never re-activated by calling this again.
    """
    if not ORDER_ID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order id")

    pool = await get_pool()

    # SECURITY: check ownership BEFORE spending an outbound Cashfree call on this order id
    async with pool.acquire() as conn:
        owner_row = await conn.fetchrow(
            "SELECT user_id FROM core.subscriptions WHERE cashfree_order_id = $1",
            order_id,
        )
    if not owner_row or str(owner_row["user_id"]) != str(user["user_id"]):
        raise HTTPException(status_code=403, detail="Order not found or does not belong to you")

    # One HTTP client for both Cashfree calls (the client must still be open for the second one)
    cf_payment_id = None
    amount_paid = None
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

        if order_status == "PAID":
            cf_payment_id = str(cf_order.get("cf_order_id", "unknown"))
            try:
                pay_resp = await client.get(
                    f"{CASHFREE_BASE_URL}/orders/{order_id}/payments",
                    headers=CASHFREE_HEADERS,
                    timeout=10.0,
                )
                if pay_resp.status_code == 200:
                    successful = [p for p in (pay_resp.json() or []) if str(p.get("payment_status", "")).upper() == "SUCCESS"]
                    if successful:
                        cf_payment_id = str(successful[0].get("cf_payment_id", cf_payment_id))
                        amount_paid = float(successful[0].get("payment_amount") or 0) or None
            except Exception as exc:
                print(f"[Payments] payment-id lookup failed for {order_id}: {exc}")

    order_amount = cf_order.get("order_amount")

    async with pool.acquire() as conn:
        if order_status == "PAID":
            result = await activate_subscription(
                conn,
                order_id,
                cf_payment_id or "unknown",
                amount_paid if amount_paid is not None else float(order_amount or 0),
                order_amount=float(order_amount) if order_amount is not None else None,
            )
            if result and result.get("activated"):
                PAYMENT_SUCCESS.labels(plan_id=result.get("plan_id", "unknown")).inc()

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
    Marks the user's paid Monthly/Yearly subscription as cancelled.
    Nothing is charged automatically, so this only records the decision. Access continues
    until the end of the period that was paid for (see the Refund Policy). Lifetime plans are a
    single payment and cannot be cancelled.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE core.subscriptions
            SET status = 'cancelled', updated_at = NOW()
            WHERE user_id = $1
              AND status = 'active'
              AND plan_id <> 'lifetime'
              AND expires_at IS NOT NULL
              AND expires_at > NOW()
            """,
            user["user_id"],
        )
        has_lifetime = False
        if result == "UPDATE 0":
            has_lifetime = bool(await conn.fetchval(
                "SELECT 1 FROM core.subscriptions WHERE user_id = $1 AND plan_id = 'lifetime' "
                "AND status IN ('active', 'cancelled') LIMIT 1",
                user["user_id"],
            ))

    if result == "UPDATE 0":
        if has_lifetime:
            raise HTTPException(
                status_code=400,
                detail="A Lifetime plan is a one-time payment and does not renew, so there is nothing to cancel.",
            )
        raise HTTPException(status_code=404, detail="No active subscription to cancel")

    return {
        "success": True,
        "message": "Your plan will not renew. You keep full access until the end of the period you paid for.",
    }

