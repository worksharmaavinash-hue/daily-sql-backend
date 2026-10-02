"""
End-to-end regression tests for subscriptions, payments, coupons, trials, Google sign-in and paywall leaks.

Drives the REAL FastAPI app (in-process, over ASGI) against a REAL PostgreSQL + Redis.
Only Cashfree's and Google's outbound HTTP calls are faked.

Usage — LOCAL THROWAWAY databases only (it TRUNCATEs core.users / core.coupons / core.problems):
    docker run -d --name t_pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=dailysql -p 127.0.0.1:55432:5432 postgres:15
    docker run -d --name t_redis -p 127.0.0.1:56379:6379 redis:7
    export DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/dailysql REDIS_URL=redis://127.0.0.1:56379/0
    python app/create_tables.py
    python verify_billing_flows.py
(needs the packages in requirements.txt; on Windows also: pip install tzdata)
"""
import asyncio, base64, hashlib, hmac, json, os, sys, types, uuid
from datetime import datetime, timedelta, timezone

BACKEND = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:55432/dailysql")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:56379/0")

from urllib.parse import urlparse
_db_host = urlparse(os.environ["DATABASE_URL"]).hostname
if _db_host not in ("127.0.0.1", "localhost", "::1"):
    sys.exit(f"Refusing to run: this suite TRUNCATEs tables and may only run against a local throwaway database (DATABASE_URL host is {_db_host!r}).")
os.environ.update(
    JWT_SECRET="test-jwt-secret", CASHFREE_APP_ID="app", CASHFREE_SECRET_KEY="cf-secret",
    CASHFREE_ENV="sandbox", FRONTEND_URL="http://localhost:3000", BACKEND_URL="http://localhost:8000",
    GOOGLE_CLIENT_ID="gid", GOOGLE_CLIENT_SECRET="gsecret", ADMIN_SECRET="admin-secret",
)

import httpx
from app.main import app
from app.db import get_pool
from app.auth.jwt import create_access_token
from app.payments import router as pay_router
from app.payments import subscription_service as S
from app.auth import router as auth_router

NOW = lambda: datetime.now(timezone.utc)
PRICE = {"monthly": 899.0, "yearly": 1499.0, "lifetime": 4999.0}

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   <- {detail}" if (not cond and detail) else ""))


# ── fake Cashfree / Google -----------------------------------------------------------------
CF = {}


def cf_reset(status="PAID", amount=899.0):
    CF.clear()
    CF.update(status=status, amount=amount, cf_order_id=555,
              payments=[{"cf_payment_id": 777, "payment_status": "SUCCESS", "payment_amount": amount}], gets=0)


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, json.dumps(data)
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


class FakeCashfree:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, **kw):
        if url.endswith("/orders"):
            CF["last_order_payload"] = kw.get("json") or {}
        return FakeResp({"payment_session_id": "sess_" + uuid.uuid4().hex[:6]})
    async def get(self, url, **kw):
        CF["gets"] += 1
        if url.endswith("/payments"):
            return FakeResp(CF["payments"])
        return FakeResp({"order_status": CF["status"], "order_amount": CF["amount"], "cf_order_id": CF["cf_order_id"]})


pay_router.httpx = types.SimpleNamespace(AsyncClient=FakeCashfree, HTTPStatusError=httpx.HTTPStatusError)

GOOGLE = {}


class FakeGoogle:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, **kw): return FakeResp({"access_token": "gtok"})
    async def get(self, url, **kw): return FakeResp(GOOGLE["userinfo"])


auth_router.httpx = types.SimpleNamespace(AsyncClient=FakeGoogle, HTTPStatusError=httpx.HTTPStatusError)

# ── helpers ---------------------------------------------------------------------------------
client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", follow_redirects=False)


async def db():
    return await get_pool()


async def q(sql, *a):
    p = await db()
    async with p.acquire() as c:
        return await c.fetch(sql, *a)


async def q1(sql, *a):
    r = await q(sql, *a)
    return r[0] if r else None


async def x(sql, *a):
    p = await db()
    async with p.acquire() as c:
        return await c.execute(sql, *a)


async def new_user(email=None, plan="free", plan_exp=None, trial_exp=None, trial_type=None, created=None, provider="email", provider_id=None):
    uid = str(uuid.uuid4())
    email = email or f"u{uuid.uuid4().hex[:8]}@example.com"
    # A number on file so create-order's phone_required check (added alongside this test run — see
    # payments/router.py's customer_phone fallback chain) doesn't block every test that creates an
    # order. Tests that specifically exercise phone handling override/clear this themselves.
    await x("""INSERT INTO core.users (user_id, email, hashed_password, auth_provider, provider_id, plan, plan_expires_at,
                                       trial_expires_at, trial_type, created_at, onboarding_completed, whatsapp_number)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,COALESCE($10, NOW()), TRUE, '9876543210')""",
            uid, email, "x", provider, provider_id, plan, plan_exp, trial_exp, trial_type, created)
    return uid, email


def hdr(uid, email, admin=False):
    return {"Authorization": "Bearer " + create_access_token(uid, email, admin)}


def sign(body: bytes, ts="1700000000"):
    return base64.b64encode(hmac.new(b"cf-secret", ts.encode() + body, hashlib.sha256).digest()).decode()


async def webhook(payload, tamper=False, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    sig = sign(body)
    if tamper:
        body = body + b" "
    return await client.post("/api/payments/webhook", content=body,
                             headers={"x-webhook-timestamp": "1700000000", "x-webhook-signature": sig})


def wh_success(oid, amount):
    return {"type": "PAYMENT_SUCCESS_WEBHOOK",
            "data": {"order": {"order_id": oid, "order_amount": amount},
                     "payment": {"cf_payment_id": 777, "payment_amount": amount}}}


async def create_order(uid, email, plan, customer_phone=None):
    cf_reset(amount=PRICE[plan])
    body = {"plan_id": plan}
    if customer_phone is not None:
        body["customer_phone"] = customer_phone
    r = await client.post("/api/payments/create-order", json=body, headers=hdr(uid, email))
    return r


async def order_for(uid, email, plan):
    r = await create_order(uid, email, plan)
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()["order_id"]


async def verify(uid, email, oid):
    return await client.get(f"/api/payments/verify-order/{oid}", headers=hdr(uid, email))


async def sub(oid):
    return await q1("SELECT * FROM core.subscriptions WHERE cashfree_order_id=$1", oid)


async def usr(uid):
    return await q1("SELECT * FROM core.users WHERE user_id=$1", uid)


async def has_access(uid):
    p = await db()
    async with p.acquire() as c:
        return await S.has_active_subscription(c, uid)


async def reset_launch(active=False, start=None, end=None):
    await x("""UPDATE core.launch_config SET is_active=$1, trial_start=$2, trial_end=$3, trial_days=30,
               new_user_trial_days=7, coupon_grace_days=2 WHERE id=1""", active, start, end)


async def sweep():
    await x("SELECT core.expire_stale_subscriptions()")


# ══════════════════════════ PAYMENTS: #1 #2 #3 #9 #10 ═══════════════════════════════════════
async def t_customer_phone():
    print("\n[#15] Cashfree order carries the customer's real phone number — priority chain + required check")
    uid, em = await new_user()
    await x("UPDATE core.users SET whatsapp_number=$1 WHERE user_id=$2", "+91 98765 43211", uid)
    await order_for(uid, em, "monthly")
    check("a stored WhatsApp number is sent, normalised to its last 10 digits",
          CF["last_order_payload"]["customer_details"]["customer_phone"] == "9876543211",
          CF["last_order_payload"]["customer_details"]["customer_phone"])

    uid, em = await new_user()
    await x("UPDATE core.users SET whatsapp_number='9876543211', phone_number=$1 WHERE user_id=$2", "+91 90000 11111", uid)
    await order_for(uid, em, "monthly")
    check("a saved billing phone_number wins over whatsapp_number",
          CF["last_order_payload"]["customer_details"]["customer_phone"] == "9000011111",
          CF["last_order_payload"]["customer_details"]["customer_phone"])

    uid, em = await new_user()
    await x("UPDATE core.users SET whatsapp_number='9876543211', phone_number='9000011111' WHERE user_id=$1", uid)
    r = await create_order(uid, em, "monthly", customer_phone="98 765-43212")
    assert r.status_code == 200, (r.status_code, r.text)
    check("a number typed at checkout wins over everything stored",
          CF["last_order_payload"]["customer_details"]["customer_phone"] == "9876543212",
          CF["last_order_payload"]["customer_details"]["customer_phone"])

    uid, em = await new_user()
    await x("UPDATE core.users SET whatsapp_number=NULL, phone_number=NULL WHERE user_id=$1", uid)
    r = await create_order(uid, em, "monthly")
    check("no number anywhere -> 400 phone_required (no more fake placeholder sent to Cashfree)",
          r.status_code == 400 and r.json().get("detail") == "phone_required", (r.status_code, r.text))


async def t_create_order_rules():
    print("\n[#3] who may buy")
    uid, em = await new_user(trial_exp=NOW() + timedelta(days=3), trial_type="new_signup")
    r = await create_order(uid, em, "monthly")
    check("trial user CAN create an order (was HTTP 409)", r.status_code == 200, r.text)

    uid, em = await new_user(plan="lifetime")
    r = await create_order(uid, em, "monthly")
    check("lifetime holder is refused (409)", r.status_code == 409, str(r.status_code))

    uid, em = await new_user(plan="yearly", plan_exp=NOW() + timedelta(days=100))
    r = await create_order(uid, em, "monthly")
    check("yearly holder buying monthly is refused (409)", r.status_code == 409 and r.json()["detail"] == "already_on_higher_plan", r.text)
    r = await create_order(uid, em, "lifetime")
    check("yearly holder CAN upgrade to lifetime", r.status_code == 200, r.text)

    uid, em = await new_user(plan="monthly", plan_exp=NOW() + timedelta(days=5))
    r = await create_order(uid, em, "monthly")
    check("monthly holder CAN renew early", r.status_code == 200, r.text)


async def t_activation_idempotent():
    print("\n[#1] activation happens exactly once")
    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    r = await verify(uid, em, oid)
    s1 = await sub(oid)
    check("first verify-order activates the plan", r.json()["subscription"] and s1["status"] == "active" and (await usr(uid))["plan"] == "monthly", r.text)
    exp1 = s1["expires_at"]

    await asyncio.sleep(1.1)
    await verify(uid, em, oid)
    await webhook(wh_success(oid, 899.0))
    check("repeat verify-order + late webhook do NOT move the expiry", (await sub(oid))["expires_at"] == exp1)

    # simulate the paid month running out; Cashfree still says PAID forever
    await x("UPDATE core.subscriptions SET expires_at=NOW()-interval '1 day' WHERE cashfree_order_id=$1", oid)
    await x("UPDATE core.users SET plan_expires_at=NOW()-interval '1 day' WHERE user_id=$1", uid)
    r = await verify(uid, em, oid)
    check("expired plan is NOT re-activated by calling verify-order again",
          r.json()["subscription"] is None and not await has_access(uid), r.text)


async def t_concurrent_activation():
    print("\n[#1] webhook + verify-order racing")
    uid, em = await new_user()
    oid = await order_for(uid, em, "yearly")
    CF.update(amount=1499.0)
    res = await asyncio.gather(
        verify(uid, em, oid), verify(uid, em, oid), verify(uid, em, oid),
        webhook(wh_success(oid, 1499.0)), webhook(wh_success(oid, 1499.0)),
    )
    s = await sub(oid)
    check("all 5 concurrent calls succeed", all(r.status_code == 200 for r in res), str([r.status_code for r in res]))
    check("exactly one activation happened (single consistent expiry)", s["status"] == "active" and s["expires_at"] is not None)
    days = (s["expires_at"] - NOW()).days
    check("yearly expiry is ~365 days, not extended by the racers", 363 <= days <= 365, str(days))


async def t_cancel_keeps_access():
    print("\n[#13] cancel keeps access until the paid period ends")
    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    await verify(uid, em, oid)
    r = await client.post("/api/payments/cancel", json={}, headers=hdr(uid, em))
    check("cancel succeeds", r.status_code == 200, r.text)
    await sweep()
    check("still has access right after cancel + sweep (was: downgraded at next restart)",
          await has_access(uid) and (await usr(uid))["plan"] == "monthly")
    r = await verify(uid, em, oid)
    check("verify-order does not resurrect a cancelled order's status", (await sub(oid))["status"] == "cancelled", str((await sub(oid))["status"]))
    r = await client.get("/api/payments/my-subscription", headers=hdr(uid, em))
    check("cancelled plan is still reported (with its status) until it ends", r.json()["subscription"] and r.json()["subscription"]["status"] == "cancelled", r.text)
    await x("UPDATE core.subscriptions SET expires_at=NOW()-interval '1 hour' WHERE cashfree_order_id=$1", oid)
    await x("UPDATE core.users SET plan_expires_at=NOW()-interval '1 hour' WHERE user_id=$1", uid)
    await sweep()
    check("after the period really ends the sweep downgrades", (await usr(uid))["plan"] == "free" and (await sub(oid))["status"] == "expired")

    uid, em = await new_user()
    oid = await order_for(uid, em, "lifetime")
    CF.update(amount=4999.0)
    await verify(uid, em, oid)
    r = await client.post("/api/payments/cancel", json={}, headers=hdr(uid, em))
    check("cancelling a lifetime plan is refused with an explanation (400)", r.status_code == 400, r.text)


async def t_refund_dispute():
    print("\n[#2] refunds, partial refunds and chargebacks")
    uid, em = await new_user()
    oid = await order_for(uid, em, "lifetime")
    CF.update(amount=4999.0)
    await verify(uid, em, oid)
    check("lifetime active before refund", (await usr(uid))["plan"] == "lifetime")
    body = {"type": "REFUND_STATUS_WEBHOOK", "data": {"refund": {"order_id": oid, "refund_amount": 4999.0, "refund_status": "SUCCESS"}}}
    r = await webhook(body)
    check("refund webhook accepted", r.status_code == 200)
    s = await sub(oid)
    check("subscription marked refunded with amount", s["status"] == "refunded" and float(s["refunded_amount"]) == 4999.0, str(s["status"]))
    check("user loses access after a full refund", (await usr(uid))["plan"] == "free" and not await has_access(uid))
    r = await verify(uid, em, oid)
    check("verify-order can NOT bring a refunded order back (Cashfree still says PAID)", r.json()["subscription"] is None and not await has_access(uid))

    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    await verify(uid, em, oid)
    part = {"type": "REFUND_STATUS_WEBHOOK", "data": {"refund": {"order_id": oid, "refund_amount": 100.0, "refund_status": "SUCCESS"}}}
    await webhook(part)
    check("partial refund is recorded but access is kept", (await sub(oid))["status"] == "active" and float((await sub(oid))["refunded_amount"]) == 100.0 and await has_access(uid))
    await webhook({"type": "REFUND_STATUS_WEBHOOK", "data": {"refund": {"order_id": oid, "refund_amount": 899.0, "refund_status": "PENDING"}}})
    check("a PENDING refund does not revoke yet", (await sub(oid))["status"] == "active")

    uid, em = await new_user()
    oid = await order_for(uid, em, "yearly")
    CF.update(amount=1499.0)
    await verify(uid, em, oid)
    await webhook({"type": "DISPUTE_CREATED", "data": {"dispute": {"order_id": oid}}})
    check("chargeback (dispute) suspends the access it gave", (await sub(oid))["status"] == "disputed" and not await has_access(uid))

    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    await webhook({"type": "REFUND_STATUS_WEBHOOK", "data": {"refund": {"order_id": oid, "refund_amount": 899.0, "refund_status": "SUCCESS"}}})
    check("refund of a never-activated (pending) order blocks a later activation",
          (await sub(oid))["status"] == "refunded" and (await verify(uid, em, oid)).json()["subscription"] is None)


async def t_no_downgrade_and_amount():
    print("\n[#9] late activation must not downgrade; amounts must match")
    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")               # pending monthly order created earlier...
    await x("UPDATE core.users SET plan='lifetime', plan_expires_at=NULL WHERE user_id=$1", uid)   # ...user then got lifetime
    await verify(uid, em, oid)
    check("paying an old monthly order does not downgrade a lifetime user", (await usr(uid))["plan"] == "lifetime")

    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    CF.update(amount=1.0)                                     # gateway reports a wrong order amount
    r = await verify(uid, em, oid)
    check("wrong order amount is NOT activated", (await sub(oid))["status"] == "pending" and r.json()["subscription"] is None)

    print("\n[#1] renewal / upgrade paid time is preserved")
    uid, em = await new_user(plan="monthly", plan_exp=NOW() + timedelta(days=10))
    await x("INSERT INTO core.subscriptions (user_id,plan_id,status,cashfree_order_id,starts_at,expires_at,amount_paid) VALUES ($1,'monthly','active',$2,NOW(),$3,899)",
            uid, "dsql_monthly_0000000000", NOW() + timedelta(days=10))
    oid = await order_for(uid, em, "monthly")
    await verify(uid, em, oid)
    d = ((await sub(oid))["expires_at"] - NOW()).days
    check("renewing while live extends from the current expiry (~40 days, not 30)", 38 <= d <= 40, str(d))

    uid, em = await new_user(plan="monthly", plan_exp=NOW() + timedelta(days=10))
    oid = await order_for(uid, em, "yearly")
    CF.update(amount=1499.0)
    await verify(uid, em, oid)
    u = await usr(uid)
    d = (u["plan_expires_at"] - NOW()).days
    check("monthly -> yearly upgrade applies the yearly plan", u["plan"] == "yearly")
    check("...and STACKS on the monthly plan's remaining 10 days (~375 days, not 365)", 373 <= d <= 375, str(d))

    print("\n[#1b] buying a paid plan mid-trial stacks onto the trial's remaining time")
    uid, em = await new_user(trial_exp=NOW() + timedelta(days=4), trial_type="new_signup")
    oid = await order_for(uid, em, "monthly")
    CF.update(amount=899.0)
    await verify(uid, em, oid)
    u = await usr(uid)
    d = (u["plan_expires_at"] - NOW()).days
    check("paid plan starts after the trial ends, not today (~34 days, not 30)", 33 <= d <= 34, str(d))
    check("the trial itself is ended now that paid access covers it", u["trial_expires_at"] <= NOW() + timedelta(seconds=5))

    print("\n[#1c] a plain first purchase (no live plan, no live trial) is unaffected")
    uid, em = await new_user()
    oid = await order_for(uid, em, "monthly")
    CF.update(amount=899.0)
    await verify(uid, em, oid)
    d = ((await usr(uid))["plan_expires_at"] - NOW()).days
    check("fresh monthly purchase is ~30 days, not stacked onto anything", 29 <= d <= 30, str(d))


async def t_verify_hardening():
    print("\n[#10] verify-order input/ownership")
    a, ea = await new_user()
    b, eb = await new_user()
    oid = await order_for(a, ea, "monthly")
    CF["gets"] = 0
    r = await verify(b, eb, oid)
    check("another user's order -> 403 and NO outbound Cashfree call", r.status_code == 403 and CF["gets"] == 0, f"{r.status_code} gets={CF['gets']}")
    r = await client.get("/api/payments/verify-order/COUPON_ABC", headers=hdr(a, ea))
    check("non-Cashfree order id -> 400", r.status_code == 400, str(r.status_code))
    r = await client.get("/api/payments/verify-order/dsql_monthly_zzzz", headers=hdr(a, ea))
    check("malformed order id -> 400", r.status_code == 400)
    r = await verify(a, ea, oid)
    s = await sub(oid)
    check("real payment id is now stored (was: silently never looked up)", s["cashfree_payment_id"] == "777", str(s["cashfree_payment_id"]))


async def t_webhook_security():
    print("\n[L1] webhook signature handling")
    r = await webhook({"type": "PAYMENT_SUCCESS_WEBHOOK", "data": {}}, tamper=True)
    check("tampered body -> 401", r.status_code == 401)
    body = b"\xff\xfe\xfa"
    r = await client.post("/api/payments/webhook", content=body, headers={"x-webhook-timestamp": "1", "x-webhook-signature": "AAAA"})
    check("non-UTF-8 body -> 401 (was: unhandled 500)", r.status_code == 401, str(r.status_code))
    r = await client.post("/api/payments/webhook", content=b"{}")
    check("missing signature headers -> 401", r.status_code == 401)


# ══════════════════════════ TRIALS: #4 #7 #8 ════════════════════════════════════════════════
async def t_trial_never_reopens():
    print("\n[#4] an ended trial stays ended (no restart-dependent access)")
    start = NOW() - timedelta(days=10)
    await reset_launch(True, start, NOW() + timedelta(days=20))
    uid, em = await new_user(trial_exp=NOW() - timedelta(hours=1), trial_type="new_signup", created=NOW() - timedelta(days=8))
    b = await has_access(uid)
    await sweep()
    a = await has_access(uid)
    check("expired signup trial: no access before the sweep", b is False)
    check("expired signup trial: STILL no access after the sweep/restart", a is False)
    row = await usr(uid)
    check("trial history is kept by the sweep", row["trial_type"] == "new_signup" and row["trial_expires_at"] is not None)

    uid2, _ = await new_user(created=start - timedelta(days=5))
    check("pre-existing user with no trial record still gets the launch window", await has_access(uid2))
    uid3, _ = await new_user(created=start + timedelta(days=1))
    check("user who joined DURING the window without a trial does not get free access", not await has_access(uid3))
    await reset_launch(False)


async def t_launch_toggle():
    print("\n[#8] launch trial on/off semantics")
    await x("TRUNCATE core.users CASCADE")
    await reset_launch(False)
    old, _ = await new_user(created=NOW() - timedelta(days=30))
    signup, _ = await new_user(trial_exp=NOW() + timedelta(days=5), trial_type="new_signup")
    used, _ = await new_user(trial_exp=NOW() - timedelta(days=1), trial_type="new_signup")
    p = await db()
    async with p.acquire() as c:
        await S.set_launch_config(c, True, trial_days=30)
    cfg1 = await q1("SELECT * FROM core.launch_config WHERE id=1")
    check("turning ON grants a global trial to a plain free user", (await usr(old))["trial_type"] == "global_trial" and await has_access(old))
    check("...but not to someone who already used their signup trial", (await usr(used))["trial_type"] == "new_signup" and not await has_access(used))

    await asyncio.sleep(1.1)
    async with p.acquire() as c:
        await S.set_launch_config(c, True, trial_days=30)         # plain re-save
    cfg2 = await q1("SELECT * FROM core.launch_config WHERE id=1")
    check("re-saving while running does NOT restart the window", cfg1["trial_start"] == cfg2["trial_start"] and cfg1["trial_end"] == cfg2["trial_end"])

    async with p.acquire() as c:
        await S.set_launch_config(c, True, trial_days=45)         # explicit extension
    cfg3 = await q1("SELECT * FROM core.launch_config WHERE id=1")
    check("changing trial_days extends the running window", (cfg3["trial_end"] - cfg3["trial_start"]).days == 45)
    check("live global trials follow the extension", (await usr(old))["trial_expires_at"] == cfg3["trial_end"])

    async with p.acquire() as c:
        await S.set_launch_config(c, False)
    check("turning OFF ends global trials immediately (was: they kept working)", not await has_access(old))
    check("...but honours already-granted personal signup trials", await has_access(signup))
    await reset_launch(False)


async def t_one_trial_per_mailbox():
    print("\n[#7] one trial per mailbox")
    await x("TRUNCATE core.users CASCADE")
    await reset_launch(True, NOW() - timedelta(days=1), NOW() + timedelta(days=29))
    p = await db()
    first, _ = await new_user(email="Jane.Doe@gmail.com")
    async with p.acquire() as c:
        got_first = await S.apply_new_user_trial(c, first)
    check("first signup gets the trial", got_first is True)
    for alias in ["janedoe+promo@gmail.com", "j.a.n.e.d.o.e@googlemail.com", "JANEDOE@gmail.com", "jane.doe+2@gmail.com"]:
        u, _ = await new_user(email=alias)
        async with p.acquire() as c:
            got = await S.apply_new_user_trial(c, u)
        check(f"alias {alias} gets NO second trial", got is False)
    other, _ = await new_user(email="someone.else@gmail.com")
    async with p.acquire() as c:
        check("a different mailbox still gets a trial", await S.apply_new_user_trial(c, other) is True)
    await reset_launch(False)


# ══════════════════════════ COUPONS: #6 ═════════════════════════════════════════════════════
async def add_coupon(email, code=None, expires=None):
    code = code or "DSQL-LT-" + uuid.uuid4().hex[:8].upper()
    await x("INSERT INTO core.coupons (code,email,plan_granted,is_used,expires_at) VALUES ($1,$2,'lifetime',FALSE,$3)", code, email, expires)
    return code


async def t_coupons():
    print("\n[#6] coupon redemption is atomic")
    uid, em = await new_user()
    code = await add_coupon(em)
    r = await client.post("/api/coupons/redeem", json={"code": code.lower()}, headers=hdr(uid, em))
    c = await q1("SELECT * FROM core.coupons WHERE code=$1", code)
    check("normal redemption works", r.status_code == 200 and c["is_used"] and (await usr(uid))["plan"] == "lifetime", r.text)
    r = await client.post("/api/coupons/redeem", json={"code": code}, headers=hdr(uid, em))
    check("second redemption is refused", r.status_code == 400)

    ghost, gem = str(uuid.uuid4()), "ghost@example.com"                        # valid token, but no such user row
    code = await add_coupon(gem)
    r = await client.post("/api/coupons/redeem", json={"code": code}, headers=hdr(ghost, gem))
    c = await q1("SELECT * FROM core.coupons WHERE code=$1", code)
    check("failure while granting rolls back: coupon is NOT burned", r.status_code == 400 and c["is_used"] is False, f"{r.status_code} used={c['is_used']}")

    uid, em = await new_user()
    code = await add_coupon(em)
    rs = await asyncio.gather(*[client.post("/api/coupons/redeem", json={"code": code}, headers=hdr(uid, em)) for _ in range(6)])
    ok = [r for r in rs if r.status_code == 200]
    n = (await q1("SELECT count(*) AS n FROM core.subscriptions WHERE cashfree_order_id=$1", "COUPON_" + code))["n"]
    check("6 simultaneous redemptions -> exactly one wins", len(ok) == 1 and n == 1, f"wins={len(ok)} subs={n}")

    other, oem = await new_user()
    code = await add_coupon(em)
    r = await client.post("/api/coupons/redeem", json={"code": code}, headers=hdr(other, oem))
    check("someone else's coupon is refused", r.status_code == 400 and "different email" in r.text)
    code = await add_coupon(oem, expires=NOW() - timedelta(days=1))
    r = await client.post("/api/coupons/redeem", json={"code": code}, headers=hdr(other, oem))
    check("expired coupon is refused", r.status_code == 400 and "expired" in r.text)


# ══════════════════════════ ADMIN: #12 ══════════════════════════════════════════════════════
async def t_admin_grant_revoke():
    print("\n[#12] admin grant / revoke")
    admin = hdr(str(uuid.uuid4()), "boss@dailysql.in", admin=True)
    uid, em = await new_user()
    r = await client.post("/admin/subscriptions/grant", json={"email": em, "plan_id": "lifetime", "reason": "support ticket 7"}, headers=admin)
    s = await q1("SELECT * FROM core.subscriptions WHERE user_id=$1 AND plan_id='lifetime'", uid)
    check("grant works and records WHO granted it", r.status_code == 200 and "boss@dailysql.in" in (s["granted_by"] or ""), r.text)
    r = await client.post("/admin/subscriptions/grant", json={"email": em, "plan_id": "monthly"}, headers=admin)
    check("downgrading a lifetime user is refused by default (409)", r.status_code == 409, str(r.status_code))
    r = await client.post("/admin/subscriptions/grant", json={"email": em, "plan_id": "monthly", "duration_days": -5, "allow_downgrade": True}, headers=admin)
    check("negative duration rejected (400)", r.status_code == 400)
    r = await client.post("/admin/subscriptions/grant", json={"email": em, "plan_id": "monthly", "duration_days": 99999}, headers=admin)
    check("absurd duration rejected (400)", r.status_code == 400)

    # paid order + admin revoke: the user must NOT be able to bring it back through verify-order
    uid, em = await new_user()
    oid = await order_for(uid, em, "yearly")
    CF.update(amount=1499.0)
    await verify(uid, em, oid)
    r = await client.post("/admin/subscriptions/grant", json={"email": em, "plan_id": "free", "reason": "abuse"}, headers=admin)
    s = await sub(oid)
    check("revoke ('free') returns to free and marks the subscription revoked", r.status_code == 200 and (await usr(uid))["plan"] == "free" and s["status"] == "revoked", r.text)
    await verify(uid, em, oid)
    check("revoked order can NOT be re-activated via verify-order", (await sub(oid))["status"] == "revoked" and not await has_access(uid))


# ══════════════════════════ GOOGLE: #5 ══════════════════════════════════════════════════════
async def google_login(userinfo):
    GOOGLE["userinfo"] = userinfo
    state = auth_router._signer.dumps("oauth-state")
    return await client.get("/auth/google/callback", params={"code": "c", "state": state})


async def t_google():
    print("\n[#5] Google sign-in")
    victim, vem = await new_user(email="victim@corp.com", provider="email")
    r = await google_login({"sub": "attacker-sub", "email": "victim@corp.com", "email_verified": False, "name": "x"})
    check("UNVERIFIED Google email is rejected", "error=email_not_verified" in r.headers.get("location", ""), r.headers.get("location", ""))
    check("...and the victim's account was not linked", (await usr(victim))["provider_id"] is None)

    r = await google_login({"sub": "real-sub", "email": "Victim@Corp.com", "email_verified": True, "name": "V"})
    loc = r.headers.get("location", "")
    u = await usr(victim)
    check("verified email (any case) links to the existing account and signs in", "/auth/callback?token=" in loc and u["provider_id"] == "real-sub", loc)
    check("password login still possible: auth_provider NOT overwritten", u["auth_provider"] == "email", u["auth_provider"])

    r = await google_login({"sub": "different-sub", "email": "victim@corp.com", "email_verified": True, "name": "V"})
    check("same email but a DIFFERENT Google identity is refused", "error=account_conflict" in r.headers.get("location", ""), r.headers.get("location", ""))

    r = await google_login({"sub": "new-sub", "email": "Brand.New@Corp.com", "email_verified": True, "name": "N"})
    n = await q1("SELECT email FROM core.users WHERE provider_id='new-sub'")
    check("new Google user is created with a normalised (lower-case) email", n and n["email"] == "brand.new@corp.com", str(n))


async def t_login_case():
    print("\n[#7] email/password login and case")
    from app.auth.router import _hash_password
    uid = str(uuid.uuid4())
    await x("INSERT INTO core.users (user_id,email,hashed_password,auth_provider,onboarding_completed) VALUES ($1,$2,$3,'email',TRUE)",
            uid, "Mixed.Case@example.com", _hash_password("correct-horse-battery"))
    r = await client.post("/auth/login", json={"email": "mixed.case@example.com", "password": "correct-horse-battery"})
    check("login works regardless of email case", r.status_code == 200, r.text)
    r = await client.post("/auth/login", json={"email": "mixed.case@example.com", "password": "wrong-password-xx"})
    check("wrong password still rejected", r.status_code == 401)


# ══════════════════════════ LEAKS: #14 ══════════════════════════════════════════════════════
async def t_leaks():
    print("\n[#14] paywall leaks")
    await x("TRUNCATE core.problems CASCADE")
    long_desc = "X" * 900
    ids = []
    for i in range(1, 33):                                  # 32 SQL problems, rows 1..32
        pid = str(uuid.uuid4())
        ids.append(pid)
        await x("INSERT INTO core.problems (id,title,difficulty,description,estimated_time_minutes,challenge_type,row_number,is_active) "
                "VALUES ($1,$2,'easy',$3,5,'sql',$4,TRUE)", pid, f"SQL {i}", long_desc, i)
    dsa = str(uuid.uuid4())
    await x("INSERT INTO core.problems (id,title,difficulty,description,estimated_time_minutes,challenge_type,row_number,is_active) "
            "VALUES ($1,'DSA 1','easy',$2,5,'python_dsa',33,TRUE)", dsa, long_desc)
    await x("INSERT INTO core.problem_solutions (problem_id, reference_query, function_name, starter_code) VALUES ($1,'x','solve','def solve(): pass')", dsa)

    r = await client.get("/problems")
    items = {p["id"]: p for p in r.json()}
    free, locked = items[ids[0]], items[ids[31]]
    check("free problem keeps its full description", len(free["description"]) == 900 and free["is_locked"] is False)
    check("locked SQL problem shows only a short teaser", locked["is_locked"] and len(locked["description"]) <= 201, str(len(locked["description"])))
    check("locked DSA problem hides its description AND starter code", items[dsa]["is_locked"] and len(items[dsa]["description"]) <= 201 and items[dsa]["starter_code"] is None)

    # today's free SQL daily problem beyond #30 must show as unlocked
    await x("INSERT INTO core.daily_practice (date, easy_problem_id) VALUES (((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date, $1)", ids[31])
    r = await client.get("/problems")
    check("today's free SQL daily problem is unlocked in the list", {p['id']: p for p in r.json()}[ids[31]]["is_locked"] is False)
    await x("DELETE FROM core.daily_practice")

    owner, oem = await new_user()
    await x("UPDATE core.users SET username='solver' WHERE user_id=$1", owner)
    await x("INSERT INTO core.user_solutions (user_id, problem_id, submitted_query) VALUES ($1,$2,'SELECT secret'), ($1,$3,'SELECT free')", owner, ids[31], ids[0])
    r = await client.get(f"/u/solver/solutions/{ids[31]}")
    check("anonymous viewer can NOT read a saved solution of a locked problem (403)", r.status_code == 403, r.text)
    r = await client.get(f"/u/solver/solutions/{ids[0]}")
    check("saved solution of a FREE problem stays public", r.status_code == 200 and r.json()["submitted_query"] == "SELECT free")
    v, vem = await new_user()
    r = await client.get(f"/u/solver/solutions/{ids[31]}", headers=hdr(v, vem))
    check("free logged-in viewer is refused too", r.status_code == 403)
    p, pem = await new_user(plan="lifetime")
    r = await client.get(f"/u/solver/solutions/{ids[31]}", headers=hdr(p, pem))
    check("paid viewer can read it", r.status_code == 200 and r.json()["submitted_query"] == "SELECT secret")


# ══════════════════════════ PROBLEM PROGRESS: acceptance, visibility, streak, app-day ═════════
async def t_problem_progress():
    print("\n[problems page] real acceptance rate, DSA visibility, streak expiry, one app-day clock")
    from datetime import date
    from app import timeutil
    from app.attempts.service import record_attempt
    from app.streaks.service import update_streak

    await x("TRUNCATE core.problems CASCADE")
    mk = lambda: str(uuid.uuid4())
    async def add_problem(title, ctype="sql", active=True, row=0):
        pid = mk()
        await x("INSERT INTO core.problems (id,title,difficulty,description,estimated_time_minutes,challenge_type,row_number,is_active) "
                "VALUES ($1,$2,'easy','d',5,$3,$4,$5)", pid, title, ctype, row, active)
        return pid

    # --- acceptance rate is real ---
    p_att, p_none = await add_problem("Attempted", row=1), await add_problem("Untouched", row=2)
    u, uem = await new_user()
    for st in ["correct", "correct", "correct", "incorrect"]:
        await x("INSERT INTO core.attempts (id,user_id,problem_id,attempt_date,status,challenge_type) VALUES ($1,$2,$3,CURRENT_DATE,$4,'sql')", mk(), u, p_att, st)
    items = {p["id"]: p for p in (await client.get("/problems")).json()}
    check("acceptance_rate = correct/attempts (75.0 for 3 of 4)", items[p_att]["acceptance_rate"] == 75.0 and items[p_att]["attempt_count"] == 4, str(items[p_att]))
    check("problem nobody attempted has acceptance_rate null (not a made-up number)", items[p_none]["acceptance_rate"] is None and items[p_none]["attempt_count"] == 0)

    # --- a DRAFT scheduled as today's DSA problem is visible (list AND detail), an unscheduled draft is not ---
    dsa_draft = await add_problem("Scheduled DSA draft", ctype="python_dsa", active=False, row=3)
    plain_draft = await add_problem("Plain draft", active=False, row=4)
    await x("INSERT INTO core.daily_practice (date, dsa_easy_problem_id) VALUES (((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date, $1)", dsa_draft)
    paid, pem = await new_user(plan="lifetime")
    ids_listed = {p["id"] for p in (await client.get("/problems")).json()}
    check("scheduled DSA draft appears in /problems", dsa_draft in ids_listed)
    check("unscheduled draft stays hidden", plain_draft not in ids_listed)
    r = await client.get(f"/problems/{dsa_draft}", headers=hdr(paid, pem))
    check("scheduled DSA draft can be opened (detail uses the same rule as the list)", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
    r = await client.get(f"/problems/{plain_draft}", headers=hdr(paid, pem))
    check("unscheduled draft detail is 404", r.status_code == 404, str(r.status_code))
    await x("DELETE FROM core.daily_practice")

    # --- streak endpoint: a dead streak reads 0 ---
    today = timeutil.app_today()
    s_user, s_em = await new_user()
    async def set_streak(n, last):
        await x("DELETE FROM core.streaks WHERE user_id=$1", s_user)
        await x("INSERT INTO core.streaks (user_id,current_streak,last_active_date) VALUES ($1,$2,$3)", s_user, n, last)
    async def streak():
        return (await client.get("/me/streak", headers=hdr(s_user, s_em))).json()
    await set_streak(5, today)
    j = await streak(); check("streak active today -> 5, active_today true", j["current_streak"] == 5 and j["active_today"] is True, str(j))
    await set_streak(5, today - timedelta(days=1))
    j = await streak(); check("last solved yesterday -> streak still 5, active_today false", j["current_streak"] == 5 and j["active_today"] is False, str(j))
    await set_streak(5, today - timedelta(days=3))
    j = await streak(); check("last solved 3 days ago -> streak is 0 (was showing a stale 5)", j["current_streak"] == 0, str(j))
    await x("DELETE FROM core.streaks WHERE user_id=$1", s_user)
    j = await streak(); check("no streak row -> 0", j["current_streak"] == 0 and j["active_today"] is False)

    # --- one clock: attempts, streaks, /me/attempts/today, heat-map all use the IST app-day ---
    real_now = timeutil.now_ist
    IST = timeutil.IST
    try:
        timeutil.now_ist = lambda: datetime(2026, 1, 15, 0, 30, tzinfo=IST)     # 00:30 IST -> app-day is still Jan 14
        check("00:30 IST belongs to the previous app-day", timeutil.app_today() == date(2026, 1, 14))
        a_user, a_em = await new_user()
        p = await add_problem("Clock problem", row=9)
        pool = await db()
        async with pool.acquire() as c:
            await record_attempt(c, a_user, p, "correct", 10)
            await update_streak(c, a_user, True)
        row = await q1("SELECT attempt_date FROM core.attempts WHERE user_id=$1", a_user)
        check("attempt stored under the app-day (Jan 14), not the server calendar date", row["attempt_date"] == date(2026, 1, 14), str(row))
        srow = await q1("SELECT last_active_date FROM core.streaks WHERE user_id=$1", a_user)
        check("streak stored under the same app-day", srow["last_active_date"] == date(2026, 1, 14))
        r = await client.get("/me/attempts/today", headers=hdr(a_user, a_em))
        check("/me/attempts/today returns it (same clock)", any(a["problem_id"] == p for a in r.json()), r.text)
        r = await client.get("/me/heatmap", headers=hdr(a_user, a_em))
        check("heat-map has the app-day key 2026-01-14", r.json().get("2026-01-14") == 1, r.text)
        j = (await client.get("/me/streak", headers=hdr(a_user, a_em))).json()
        check("streak alive and active_today at that moment", j["current_streak"] == 1 and j["active_today"] is True, str(j))

        timeutil.now_ist = lambda: datetime(2026, 1, 15, 1, 30, tzinfo=IST)     # 01:30 IST -> new app-day Jan 15
        r = await client.get("/me/attempts/today", headers=hdr(a_user, a_em))
        check("after 01:00 IST the new day starts with no attempts", r.json() == [], r.text)
        j = (await client.get("/me/streak", headers=hdr(a_user, a_em))).json()
        check("streak survives into the next day (yesterday counts) but is no longer active_today", j["current_streak"] == 1 and j["active_today"] is False, str(j))
        async with pool.acquire() as c:
            await update_streak(c, a_user, True)
        srow = await q1("SELECT current_streak,last_active_date FROM core.streaks WHERE user_id=$1", a_user)
        check("solving on the next app-day extends the streak to 2", srow["current_streak"] == 2 and srow["last_active_date"] == date(2026, 1, 15), str(srow))
    finally:
        timeutil.now_ist = real_now


async def main():
    await x("TRUNCATE core.users CASCADE")
    await x("TRUNCATE core.coupons CASCADE")
    cf_reset()
    tests = [t_create_order_rules, t_activation_idempotent, t_concurrent_activation, t_cancel_keeps_access, t_refund_dispute,
             t_no_downgrade_and_amount, t_verify_hardening, t_webhook_security, t_trial_never_reopens, t_launch_toggle,
             t_one_trial_per_mailbox, t_coupons, t_admin_grant_revoke, t_google, t_login_case, t_leaks, t_problem_progress,
             t_customer_phone]
    for t in tests:
        try:
            await t()
        except Exception as e:                     # a crashing test is a failing test
            import traceback
            check(f"{t.__name__} ran without crashing", False, repr(e))
            traceback.print_exc()
    print(f"\n==== {len(PASSED)} passed, {len(FAILED)} failed ====")
    for f in FAILED:
        print("  FAILED:", f)
    await client.aclose()
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
