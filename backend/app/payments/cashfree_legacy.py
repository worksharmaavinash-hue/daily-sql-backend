"""
Legacy Cashfree webhook — kept after the move to Razorpay so orders that were paid through Cashfree still
get their refunds and chargebacks applied (and a late PAYMENT_SUCCESS for an order created before the
switch still activates). New orders are created only through Razorpay (see router.py).

Endpoint (unchanged, so the URL configured in the Cashfree dashboard keeps working):
  POST /api/payments/webhook   → Cashfree async notification
"""
import os
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

from app.db import get_pool
from app.payments.subscription_service import (
    activate_subscription,
    get_plan_price,
    revoke_subscription,
    verify_cashfree_webhook_signature,
)
from app.metrics import PAYMENT_SUCCESS, CASHFREE_WEBHOOK_STATUS

router = APIRouter(prefix="/api/payments", tags=["payments"])

CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY", "")


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



# ─── Cashfree webhook (server-to-server, async) ──────────────────────────────
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
                    "SELECT plan_id, amount_paid, expected_amount FROM core.subscriptions WHERE cashfree_order_id = $1",
                    order_id,
                )
                paid = float(sub["amount_paid"] or 0) if sub else 0.0
                if sub and paid <= 0:
                    paid = float(sub["expected_amount"]) if sub["expected_amount"] is not None else (
                        await get_plan_price(conn, sub["plan_id"]) or 0.0
                    )
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
