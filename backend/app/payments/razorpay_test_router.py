"""
Razorpay test harness — isolated from the live Cashfree flow.

Never grants subscriptions; it only exercises Razorpay (test mode) and logs every step to
core.rzp_test_events so the admin test page can show a timeline per order.

Mounted only when RAZORPAY_TEST_HARNESS=1. Built to be safe to leave on in prod:
  - every admin route answers 404 (not 401/403) unless the caller is an admin/superadmin, so the harness is
    indistinguishable from a missing route; optional IP allowlist (RAZORPAY_HARNESS_ALLOWED_IPS) on top
  - routes are excluded from /docs and /openapi.json
  - webhook answers 404 to anything without a valid Razorpay signature
  - with live keys, amounts are capped at RAZORPAY_HARNESS_MAX_INR (default ₹10) and payments can be refunded

Endpoints:
  GET  /api/rzp-test/config            → key id, webhook URL, which secrets are set   (admin)
  POST /api/rzp-test/create-order      → create a Razorpay order for an arbitrary amount (admin)
  POST /api/rzp-test/verify            → verify checkout handler signature             (admin)
  POST /api/rzp-test/client-event      → log checkout-side events (failed / dismissed)  (admin)
  GET  /api/rzp-test/order/{order_id}  → server-side re-fetch of order + payments       (admin)
  POST /api/rzp-test/simulate-webhook  → self-signed fake webhook through the handler   (admin)
  GET  /api/rzp-test/logs              → recent events                                  (admin)
  DELETE /api/rzp-test/logs            → clear events                                   (admin)
  POST /api/rzp-test/refund/{pay_id}   → full refund of a harness payment               (admin)
  POST /api/rzp-test/webhook           → Razorpay webhook receiver (signature-verified, public)
"""
import os
import hmac
import json
import uuid
import time
import hashlib
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.admin.router import get_admin_api_key, require_admin_role
from app.db import get_pool

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
RAZORPAY_API = "https://api.razorpay.com/v1"
IS_LIVE = RAZORPAY_KEY_ID.startswith("rzp_live_")
MAX_INR = float(os.getenv("RAZORPAY_HARNESS_MAX_INR") or ("10" if IS_LIVE else "500000"))
ALLOWED_IPS = {ip.strip() for ip in os.getenv("RAZORPAY_HARNESS_ALLOWED_IPS", "").split(",") if ip.strip()}

_NOT_FOUND = HTTPException(status_code=404, detail="Not Found")


def _client_ip(request: Request) -> str:
    # Caddy appends the real client IP as the right-most X-Forwarded-For entry.
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "")


async def harness_guard(request: Request):
    """Admin-only, but failures look exactly like a route that doesn't exist."""
    if ALLOWED_IPS and _client_ip(request) not in ALLOWED_IPS:
        raise _NOT_FOUND
    try:
        await get_admin_api_key(request, request.headers.get("x-admin-secret"))
        await require_admin_role(request)
    except HTTPException:
        raise _NOT_FOUND


router = APIRouter(prefix="/api/rzp-test", tags=["razorpay-test"], include_in_schema=False)
admin = [Depends(harness_guard)]

_table_ready = False


async def _ensure_table(conn):
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS core.rzp_test_events (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            kind TEXT NOT NULL,
            ok BOOLEAN,
            order_id TEXT,
            payment_id TEXT,
            message TEXT,
            payload JSONB
        );
        CREATE INDEX IF NOT EXISTS rzp_test_events_created_idx ON core.rzp_test_events (created_at DESC);
    """)
    _table_ready = True


async def log_event(kind: str, ok: Optional[bool] = None, order_id: Optional[str] = None,
                    payment_id: Optional[str] = None, message: Optional[str] = None, payload=None):
    print(f"[rzp-test] {kind} ok={ok} order={order_id} payment={payment_id} {message or ''}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        await conn.execute(
            """INSERT INTO core.rzp_test_events (kind, ok, order_id, payment_id, message, payload)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb)""",
            kind, ok, order_id, payment_id, message, json.dumps(payload) if payload is not None else None,
        )


def _require_keys():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=500, detail="RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


# ─── Config ──────────────────────────────────────────────────────────────────
@router.get("/config", dependencies=admin)
async def config():
    return {
        "key_id": RAZORPAY_KEY_ID,
        "mode": "test" if RAZORPAY_KEY_ID.startswith("rzp_test_") else ("live" if RAZORPAY_KEY_ID else "unset"),
        "max_inr": MAX_INR,
        "ip_allowlist": bool(ALLOWED_IPS),
        "key_secret_set": bool(RAZORPAY_KEY_SECRET),
        "webhook_secret_set": bool(RAZORPAY_WEBHOOK_SECRET),
        "webhook_url": f"{BACKEND_URL.rstrip('/')}/api/rzp-test/webhook",
    }


# ─── Orders ──────────────────────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    amount_inr: float = Field(gt=0, le=500000)
    notes: Optional[str] = None


@router.post("/create-order", dependencies=admin)
async def create_order(body: CreateOrderRequest):
    _require_keys()
    amount_paise = int(round(body.amount_inr * 100))
    if amount_paise < 100:
        raise HTTPException(status_code=400, detail="Razorpay minimum is ₹1.00")
    if body.amount_inr > MAX_INR:
        raise HTTPException(status_code=400, detail=f"Harness cap is ₹{MAX_INR:g} (RAZORPAY_HARNESS_MAX_INR)")

    receipt = f"rzptest_{uuid.uuid4().hex[:12]}"
    req = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": {"source": "dailysql-rzp-test", "note": body.notes or ""},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(f"{RAZORPAY_API}/orders", json=req, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    data = res.json()
    if res.status_code >= 300:
        await log_event("order_create_failed", False, message=f"HTTP {res.status_code}", payload={"request": req, "response": data})
        raise HTTPException(status_code=502, detail=data.get("error", {}).get("description", "Razorpay order creation failed"))

    await log_event("order_created", True, order_id=data["id"], message=f"₹{amount_paise / 100:.2f}", payload=data)
    return {"order_id": data["id"], "amount": data["amount"], "currency": data["currency"], "key_id": RAZORPAY_KEY_ID}


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/verify", dependencies=admin)
async def verify_checkout(body: VerifyRequest):
    _require_keys()
    expected = _hmac_hex(RAZORPAY_KEY_SECRET, f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode())
    ok = hmac.compare_digest(expected, body.razorpay_signature)
    await log_event(
        "checkout_signature_ok" if ok else "checkout_signature_bad", ok,
        order_id=body.razorpay_order_id, payment_id=body.razorpay_payment_id, payload=body.model_dump(),
    )
    return {"signature_valid": ok}


class ClientEvent(BaseModel):
    kind: str = Field(pattern=r"^checkout_[a-z_]{1,40}$")
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    message: Optional[str] = None
    payload: Optional[dict] = None


@router.post("/client-event", dependencies=admin)
async def client_event(body: ClientEvent):
    ok = False if body.kind == "checkout_failed" else (True if body.kind == "checkout_success" else None)
    await log_event(body.kind, ok, body.order_id, body.payment_id,
                    body.message, body.payload)
    return {"ok": True}


@router.get("/order/{order_id}", dependencies=admin)
async def fetch_order(order_id: str):
    _require_keys()
    auth = (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    async with httpx.AsyncClient(timeout=15) as client:
        o = await client.get(f"{RAZORPAY_API}/orders/{order_id}", auth=auth)
        p = await client.get(f"{RAZORPAY_API}/orders/{order_id}/payments", auth=auth)
    if o.status_code >= 300:
        raise HTTPException(status_code=502, detail=o.json().get("error", {}).get("description", "fetch failed"))
    order = o.json()
    payments = p.json().get("items", []) if p.status_code < 300 else []
    summary = [{"id": x["id"], "status": x["status"], "method": x.get("method"), "amount": x["amount"],
                "error": x.get("error_description")} for x in payments]
    await log_event("server_verify", order["status"] == "paid", order_id=order_id,
                    message=f"order={order['status']} payments={[s['status'] for s in summary]}",
                    payload={"order": order, "payments": summary})
    return {"order": order, "payments": summary}


# ─── Webhook ─────────────────────────────────────────────────────────────────
_last_bad_sig_log = 0.0


async def _handle_webhook(raw_body: bytes, signature: str, event_id: str, simulated: bool):
    tag = " (simulated)" if simulated else ""
    if not RAZORPAY_WEBHOOK_SECRET:
        print("[rzp-test] webhook hit but RAZORPAY_WEBHOOK_SECRET is not set")
        raise _NOT_FOUND

    expected = _hmac_hex(RAZORPAY_WEBHOOK_SECRET, raw_body)
    if not signature or not hmac.compare_digest(expected, signature):
        global _last_bad_sig_log
        # Public endpoint: throttle so junk traffic can't flood the log table.
        if simulated or time.monotonic() - _last_bad_sig_log > 10:
            _last_bad_sig_log = time.monotonic()
            await log_event("webhook_signature_bad", False, message="X-Razorpay-Signature mismatch" + tag)
        raise _NOT_FOUND

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        await log_event("webhook_bad_json", False, message=tag)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = data.get("event", "unknown")
    pay = (data.get("payload", {}).get("payment") or {}).get("entity") or {}
    order = (data.get("payload", {}).get("order") or {}).get("entity") or {}
    order_id = pay.get("order_id") or order.get("id")
    status = pay.get("status") or order.get("status")
    ok = event in ("payment.captured", "order.paid", "payment.authorized") or None
    if event == "payment.failed":
        ok = False
    await log_event(f"webhook:{event}", ok, order_id=order_id, payment_id=pay.get("id"),
                    message=f"status={status} event_id={event_id or '-'}{tag}", payload=data)
    return {"status": "ok"}


@router.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    return await _handle_webhook(raw, request.headers.get("x-razorpay-signature", ""),
                                 request.headers.get("x-razorpay-event-id", ""), simulated=False)


class SimulateRequest(BaseModel):
    event: str = Field(default="payment.captured", pattern=r"^(payment\.captured|payment\.failed|order\.paid)$")
    order_id: Optional[str] = None
    bad_signature: bool = False


@router.post("/simulate-webhook", dependencies=admin)
async def simulate_webhook(body: SimulateRequest):
    """Feed a fake, self-signed event through the real webhook handler — tests signature + logging without a tunnel."""
    order_id = body.order_id or f"order_SIM{uuid.uuid4().hex[:10]}"
    status = {"payment.captured": "captured", "payment.failed": "failed", "order.paid": "captured"}[body.event]
    payload = {
        "entity": "event",
        "event": body.event,
        "created_at": int(time.time()),
        "payload": {"payment": {"entity": {
            "id": f"pay_SIM{uuid.uuid4().hex[:10]}", "order_id": order_id, "status": status,
            "amount": 100, "currency": "INR", "method": "upi",
        }}},
    }
    raw = json.dumps(payload).encode()
    sig = "deadbeef" if body.bad_signature else _hmac_hex(RAZORPAY_WEBHOOK_SECRET or "x", raw)
    try:
        return await _handle_webhook(raw, sig, "simulated", simulated=True)
    except HTTPException as e:
        return {"status": "rejected", "http_status": e.status_code, "detail": e.detail}


# ─── Refund ──────────────────────────────────────────────────────────────────
@router.post("/refund/{payment_id}", dependencies=admin)
async def refund(payment_id: str):
    """Full refund — for cleaning up real-money test payments made with live keys."""
    _require_keys()
    if not payment_id.startswith("pay_"):
        raise HTTPException(status_code=400, detail="Not a payment id")
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(f"{RAZORPAY_API}/payments/{payment_id}/refund", json={},
                                auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    data = res.json()
    ok = res.status_code < 300
    await log_event("refund_created" if ok else "refund_failed", ok, order_id=None, payment_id=payment_id,
                    message=data.get("status") if ok else data.get("error", {}).get("description"), payload=data)
    if not ok:
        raise HTTPException(status_code=502, detail=data.get("error", {}).get("description", "Refund failed"))
    return data


# ─── Logs ────────────────────────────────────────────────────────────────────
@router.get("/logs", dependencies=admin)
async def logs(limit: int = 200, order_id: Optional[str] = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        rows = await conn.fetch(
            """SELECT id, created_at, kind, ok, order_id, payment_id, message, payload
               FROM core.rzp_test_events
               WHERE ($2::text IS NULL OR order_id = $2)
               ORDER BY id DESC LIMIT $1""",
            min(max(limit, 1), 1000), order_id,
        )
    return [{**dict(r), "created_at": r["created_at"].isoformat(),
             "payload": json.loads(r["payload"]) if r["payload"] else None} for r in rows]


@router.delete("/logs", dependencies=admin)
async def clear_logs():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        await conn.execute("TRUNCATE core.rzp_test_events")
    return {"ok": True}
