"""
Payments router — Full subscription lifecycle via Razorpay (Orders API + Standard Checkout).

Plans can be bought in INR or USD; both prices live in core.subscription_plans and are edited from the CMS.

Endpoints:
  POST /api/payments/create-order       → Create Razorpay order & pending subscription
  POST /api/payments/verify-payment     → Checkout handler callback: verify signature, activate
  GET  /api/payments/verify-order/{id}  → Re-check an order with Razorpay (success page polling)
  POST /api/payments/razorpay/webhook   → Razorpay async notification (activate / refund / dispute)
  GET  /api/payments/my-subscription    → Current user's active plan details
  GET  /api/payments/plans              → Public plan catalogue (INR + USD prices)
  POST /api/payments/cancel             → Cancel an active subscription

The old Cashfree webhook (refunds/disputes on orders paid before the switch) lives in cashfree_legacy.py.
"""
import os
import re
import uuid
import json
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional

from app.auth.jwt import verify_jwt
from app.db import get_pool
from app.payments.subscription_service import (
    SUPPORTED_CURRENCIES,
    get_plans,
    create_pending_subscription,
    activate_subscription,
    get_active_subscription,
    get_purchase_block,
    revoke_subscription,
    verify_razorpay_signature,
)
from app.metrics import (
    CHECKOUT_INITIATED,
    PAYMENT_SUCCESS,
    RAZORPAY_WEBHOOK_STATUS,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ─── Config ──────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
RAZORPAY_API = "https://api.razorpay.com/v1"
RAZORPAY_MODE = "live" if RAZORPAY_KEY_ID.startswith("rzp_live_") else "test"

VALID_PLAN_IDS = ("monthly", "yearly", "lifetime")

# Orders created by create_order() look like dsql_<plan>_<10 hex chars>. Anything else (coupon / manual-grant
# reference numbers, or attacker-supplied text) is never looked up at Razorpay.
ORDER_ID_RE = re.compile(r"^dsql_(monthly|yearly|lifetime)_[0-9a-f]{10}$")


def _auth() -> tuple[str, str]:
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        print("[Payments] RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set")
        raise HTTPException(status_code=502, detail="Payment provider is temporarily unavailable.")
    return (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)


async def _rzp(client: httpx.AsyncClient, method: str, path: str, body: Optional[dict] = None) -> dict:
    """Call the Razorpay API; our own credential problems never look like the user's request failing."""
    try:
        resp = await client.request(method, f"{RAZORPAY_API}{path}", json=body, auth=_auth(), timeout=15.0)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay unavailable: {exc}")
    try:
        data = resp.json()
    except ValueError:
        data = {"error": {"description": resp.text[:200]}}
    if resp.status_code in (401, 403):
        print(f"[Payments] Razorpay rejected our credentials: {data}")
        raise HTTPException(status_code=502, detail="Payment provider is temporarily unavailable.")
    if resp.status_code >= 300:
        desc = (data.get("error") or {}).get("description") or "Razorpay request failed"
        print(f"[Payments] Razorpay {method} {path} → HTTP {resp.status_code}: {desc}")
        raise HTTPException(status_code=502, detail=desc)
    return data


def _major(subunits) -> float:
    """Razorpay amounts are in paise / cents; INR and USD both have two decimal places."""
    return round(int(subunits or 0) / 100.0, 2)


# ─── Pydantic models ─────────────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    plan_id: str
    currency: str = Field(default="INR")


class VerifyPaymentRequest(BaseModel):
    order_id: str                  # our dsql_<plan>_<hex> reference
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


def _clean_phone(raw: Optional[str]) -> Optional[str]:
    """Last 10 digits of a phone number, or None if it isn't a usable number (e.g. "@handle", "joined_via_link")."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else None


class CancelRequest(BaseModel):
    reason: Optional[str] = None


# ─── 1. Create Order ─────────────────────────────────────────────────────────
@router.post("/create-order")
async def create_order(
    payload: CreateOrderRequest,
    user: dict = Depends(verify_jwt),        # auth required
):
    """
    Creates a Razorpay order (INR or USD) and a pending subscription record in DB.
    Returns what the frontend needs to open Razorpay Checkout.
    """
    if payload.plan_id not in VALID_PLAN_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan_id. Must be one of: {list(VALID_PLAN_IDS)}",
        )
    currency = (payload.currency or "INR").upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency. Must be one of: {list(SUPPORTED_CURRENCIES)}")

    order_id = f"dsql_{payload.plan_id}_{uuid.uuid4().hex[:10]}"
    user_id = user["user_id"]
    user_email = user.get("email", "user@dailysql.in")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Price comes from the database (fresh read, never cached) so a CMS price change applies at once
        plans_now = await get_plans(conn, use_cache=False)
        if payload.plan_id not in plans_now:
            raise HTTPException(status_code=400, detail="This plan is not available right now.")
        plan_row = plans_now[payload.plan_id]
        amount = plan_row["price_usd"] if currency == "USD" else plan_row["price"]
        if amount is None:
            raise HTTPException(status_code=400, detail=f"This plan cannot be bought in {currency} right now.")
        plan = {"name": plan_row["name"], "amount": float(amount)}

        db_user = await conn.fetchrow(
            "SELECT full_name, email, whatsapp_number, phone_number FROM core.users WHERE user_id = $1",
            user_id,
        )
        customer_name = (db_user["full_name"] if db_user and db_user["full_name"] else "Daily SQL User")
        customer_email = (db_user["email"] if db_user and db_user["email"] else user_email)
        # Only used to prefill checkout; Razorpay asks for the number itself when we have none.
        customer_phone = (
            _clean_phone(db_user["phone_number"] if db_user else None)
            or _clean_phone(db_user["whatsapp_number"] if db_user else None)
        )

        # Trial users may buy, the same plan renews and a higher plan upgrades. Only a Lifetime holder,
        # or buying a plan lower than the one already held, is refused.
        block = await get_purchase_block(conn, user_id, payload.plan_id)
        if block:
            raise HTTPException(status_code=409, detail=block)

        async with httpx.AsyncClient() as client:
            rzp_order = await _rzp(client, "POST", "/orders", {
                "amount": int(round(plan["amount"] * 100)),
                "currency": currency,
                "receipt": order_id,
                "notes": {"dsql_order_id": order_id, "plan_id": payload.plan_id, "user_id": str(user_id)},
            })

        # Store pending subscription in DB
        await create_pending_subscription(
            conn, user_id, payload.plan_id, order_id, plan["amount"],
            currency=currency, payment_gateway="razorpay", razorpay_order_id=rzp_order["id"],
        )
        CHECKOUT_INITIATED.labels(plan_id=payload.plan_id).inc()

    return {
        "success": True,
        "order_id": order_id,
        "razorpay_order_id": rzp_order["id"],
        "key_id": RAZORPAY_KEY_ID,
        "amount": rzp_order["amount"],          # subunits, as Checkout expects
        "currency": currency,
        "order_amount": plan["amount"],
        "plan_id": payload.plan_id,
        "plan_name": plan["name"],
        "prefill": {"name": customer_name, "email": customer_email, "contact": customer_phone or ""},
        "environment": RAZORPAY_MODE,
    }


# ─── Settling an order against Razorpay ──────────────────────────────────────
async def _settle_order(conn, sub_row) -> str:
    """
    Ask Razorpay what happened to this order and activate the plan if it was paid.
    Returns PAID | ACTIVE (still awaiting payment) | FAILED. Safe to call any number of times.
    """
    rzp_order_id = sub_row["razorpay_order_id"]
    if not rzp_order_id:
        # Not a Razorpay order (e.g. paid through Cashfree before the switch): report what we already know.
        return "PAID" if sub_row["status"] in ("active", "cancelled") else (
            "ACTIVE" if sub_row["status"] == "pending" else "FAILED"
        )

    async with httpx.AsyncClient() as client:
        order = await _rzp(client, "GET", f"/orders/{rzp_order_id}")
        payments = (await _rzp(client, "GET", f"/orders/{rzp_order_id}/payments")).get("items", [])
        paid = next((p for p in payments if p.get("status") == "captured"), None)
        if paid is None:
            # Auto-capture off (or not yet run): capture an authorized payment ourselves so the money
            # is not auto-refunded by Razorpay a few days later.
            authorized = next((p for p in payments if p.get("status") == "authorized"), None)
            if authorized is not None:
                paid = await _rzp(client, "POST", f"/payments/{authorized['id']}/capture",
                                  {"amount": authorized["amount"], "currency": authorized["currency"]})

    if paid is not None:
        result = await activate_subscription(
            conn,
            sub_row["cashfree_order_id"],
            paid["id"],
            _major(paid["amount"]),
            order_amount=_major(order.get("amount")),
            currency=paid.get("currency"),
        )
        if result and result.get("activated"):
            PAYMENT_SUCCESS.labels(plan_id=result.get("plan_id", "unknown")).inc()
        elif result and result.get("reason") in ("amount_mismatch", "currency_mismatch"):
            print(f"[Payments] REFUSED to activate {sub_row['cashfree_order_id']}: {result['reason']}")
            return "FAILED"
        return "PAID"

    if any(p.get("status") in ("created", "authorized") for p in payments) or order.get("status") in ("created", "attempted"):
        return "ACTIVE"
    return "FAILED"


async def _owned_order(conn, order_id: str, user_id) -> dict:
    if not ORDER_ID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order id")
    row = await conn.fetchrow(
        "SELECT user_id, status, cashfree_order_id, razorpay_order_id FROM core.subscriptions WHERE cashfree_order_id = $1",
        order_id,
    )
    # SECURITY: check ownership BEFORE spending an outbound Razorpay call on this order id
    if not row or str(row["user_id"]) != str(user_id):
        raise HTTPException(status_code=403, detail="Order not found or does not belong to you")
    return row


# ─── 2. Checkout handler callback ────────────────────────────────────────────
@router.post("/verify-payment")
async def verify_payment(payload: VerifyPaymentRequest, user: dict = Depends(verify_jwt)):
    """
    Called by the frontend from Razorpay Checkout's success handler. The signature proves the payment
    id belongs to this order, but the plan is only activated after Razorpay itself confirms the payment
    was captured for the right amount (_settle_order).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _owned_order(conn, payload.order_id, user["user_id"])
        if row["razorpay_order_id"] != payload.razorpay_order_id:
            raise HTTPException(status_code=400, detail="Order mismatch")
        message = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
        if not verify_razorpay_signature(message, payload.razorpay_signature, RAZORPAY_KEY_SECRET):
            print(f"[Payments] Invalid checkout signature for order {payload.order_id}")
            raise HTTPException(status_code=400, detail="Payment signature verification failed")
        order_status = await _settle_order(conn, row)
        sub = await get_active_subscription(conn, user["user_id"])

    return {"success": True, "order_id": payload.order_id, "order_status": order_status, "subscription": sub}


# ─── 3. Re-check an order (success page polling) ────────────────────────────
@router.get("/verify-order/{order_id}")
async def verify_order(order_id: str, user: dict = Depends(verify_jwt)):
    """
    The success page polls this to confirm payment status. Also activates the plan if Razorpay says the
    order is paid but the webhook has not arrived yet. Safe to call any number of times: activation
    happens at most once per order, and a cancelled, expired, refunded or revoked order is never
    re-activated by calling this again.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _owned_order(conn, order_id, user["user_id"])
        order_status = await _settle_order(conn, row)
        sub = await get_active_subscription(conn, user["user_id"])

    return {
        "success": True,
        "order_id": order_id,
        "order_status": order_status,
        "subscription": sub,
    }


# ─── 4. Razorpay Webhook (server-to-server, async) ───────────────────────────
@router.post("/razorpay/webhook")
async def razorpay_webhook(request: Request):
    """
    Receives async notifications from Razorpay. Verifies X-Razorpay-Signature, then:
      - payment.captured / order.paid  → activates the plan (idempotent, exactly once)
      - refund.processed               → a fully refunded order loses its access
      - payment.dispute.created        → a chargeback suspends the access it gave
    Everything else is acknowledged and ignored.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured on server")
    if not verify_razorpay_signature(raw_body.decode("utf-8", "replace"), signature, RAZORPAY_WEBHOOK_SECRET):
        RAZORPAY_WEBHOOK_STATUS.labels(event_type="signature_verification", status="signature_error").inc()
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        RAZORPAY_WEBHOOK_STATUS.labels(event_type="json_decode", status="invalid_json").inc()
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = body.get("event", "")
    entities = body.get("payload") or {}
    payment = (entities.get("payment") or {}).get("entity") or {}
    order = (entities.get("order") or {}).get("entity") or {}
    rzp_order_id = payment.get("order_id") or order.get("id")

    if not rzp_order_id:
        RAZORPAY_WEBHOOK_STATUS.labels(event_type=event or "other", status="ignored").inc()
        return {"status": "ok"}

    pool = await get_pool()
    async with pool.acquire() as conn:
        sub = await conn.fetchrow(
            "SELECT cashfree_order_id, plan_id, amount_paid, expected_amount FROM core.subscriptions WHERE razorpay_order_id = $1",
            rzp_order_id,
        )
        if not sub:
            RAZORPAY_WEBHOOK_STATUS.labels(event_type=event or "other", status="order_not_found").inc()
            print(f"[Webhook] No subscription for razorpay_order_id={rzp_order_id} ({event})")
            return {"status": "ok"}
        order_id = sub["cashfree_order_id"]

        if event in ("payment.captured", "order.paid"):
            if payment.get("status") != "captured":
                RAZORPAY_WEBHOOK_STATUS.labels(event_type=event, status="not_captured").inc()
                return {"status": "ok"}
            result = await activate_subscription(
                conn, order_id, payment["id"], _major(payment.get("amount")),
                order_amount=_major(order["amount"]) if order.get("amount") is not None else _major(payment.get("amount")),
                currency=payment.get("currency"),
            )
            if result is None:
                status = "order_not_found"
            elif result.get("activated"):
                status = "success"
                PAYMENT_SUCCESS.labels(plan_id=result.get("plan_id", "unknown")).inc()
                print(f"[Webhook] Subscription activated: user={result['user_id']} plan={result['plan_id']}")
            else:
                status = result.get("reason", "ignored")
                if status in ("amount_mismatch", "currency_mismatch"):
                    print(f"[Webhook] REFUSED to activate {order_id}: {status}")
            RAZORPAY_WEBHOOK_STATUS.labels(event_type=event, status=status).inc()

        elif event == "refund.processed":
            # The payment entity carries the running total refunded so far.
            refunded = _major(payment.get("amount_refunded"))
            charged = _major(payment.get("amount"))
            if charged > 0 and refunded >= charged - 0.01:
                revoked = await revoke_subscription(
                    conn, order_id, "refunded", reason="Full refund via Razorpay", refunded_amount=refunded,
                )
                status = "revoked" if revoked else "nothing_to_revoke"
                print(f"[Webhook] Refund {status}: order={order_id} amount={refunded}")
            else:
                await conn.execute(
                    "UPDATE core.subscriptions SET refunded_amount = GREATEST(COALESCE(refunded_amount, 0), $2), "
                    "updated_at = NOW() WHERE cashfree_order_id = $1",
                    order_id, refunded,
                )
                status = "partial_recorded"
                print(f"[Webhook] Partial refund recorded (access kept): order={order_id} amount={refunded}")
            RAZORPAY_WEBHOOK_STATUS.labels(event_type=event, status=status).inc()

        elif event == "payment.dispute.created":
            revoked = await revoke_subscription(conn, order_id, "disputed", reason="Chargeback / dispute opened")
            RAZORPAY_WEBHOOK_STATUS.labels(event_type=event, status="revoked" if revoked else "nothing_to_revoke").inc()
            print(f"[Webhook] Dispute opened: order={order_id} access {'suspended' if revoked else 'unchanged'}")

        else:
            RAZORPAY_WEBHOOK_STATUS.labels(event_type=event or "other", status="ignored").inc()

    # Always 200 once the signature is valid — Razorpay retries non-2xx responses
    return {"status": "ok"}


# ─── 5. My Subscription ──────────────────────────────────────────────────────
@router.get("/my-subscription")
async def my_subscription(user: dict = Depends(verify_jwt)):
    """Returns the logged-in user's active subscription and trial details."""
    pool = await get_pool()
    from app.payments.subscription_service import get_user_full_access_status
    async with pool.acquire() as conn:
        status_info = await get_user_full_access_status(conn, user["user_id"])
        sub = await get_active_subscription(conn, user["user_id"])
        plans_now = await get_plans(conn)

    plan = status_info["plan"]
    details = plans_now.get(plan) if plan != "free" else None
    return {
        **status_info,
        "subscription": sub,
        "plan_details": {"name": details["name"], "amount": details["price"], "amount_usd": details["price_usd"]} if details else None,
    }


# ─── Public plan catalogue ───────────────────────────────────────────────────
@router.get("/plans")
async def list_plans():
    """Active plans with their current INR and USD prices - what the pricing and payment pages render."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        plans_now = await get_plans(conn)
    return {
        "currency": "INR",
        "currencies": list(SUPPORTED_CURRENCIES),
        "payment_mode": RAZORPAY_MODE,   # "test" with rzp_test_ keys: the frontend shows a test-mode notice
        "plans": list(plans_now.values()),
    }



# ─── 6. Cancel Subscription ──────────────────────────────────────────────────
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

