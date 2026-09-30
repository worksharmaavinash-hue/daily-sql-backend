"""
Subscription service — Reusable helpers for payments, trials, coupons, and access control.
"""
import os
import hmac
import hashlib
import base64
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any


# ─── Plan durations ──────────────────────────────────────────────────────────
PLAN_DURATIONS: dict[str, Optional[int]] = {
    "monthly": 30,
    "yearly": 365,
    "lifetime": None,   # None = never expires
}


def _compute_expires_at(plan_id: str) -> Optional[datetime]:
    """Return the UTC expiry datetime for a plan, or None for lifetime."""
    days = PLAN_DURATIONS.get(plan_id)
    if days is None:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)


PLAN_RANK: dict[str, int] = {"free": 0, "monthly": 1, "yearly": 2, "lifetime": 3}

# Single source of truth for what each plan costs (used to create AND to verify orders)
PLAN_PRICES: dict[str, float] = {"monthly": 899.00, "yearly": 1499.00, "lifetime": 4999.00}


def _live_paid_plan(plan: Optional[str], plan_expires_at: Optional[datetime], now: datetime) -> Optional[str]:
    """The paid plan that is genuinely in force right now, or None."""
    if plan == "lifetime":
        return "lifetime"
    if plan in ("monthly", "yearly") and plan_expires_at is not None and plan_expires_at > now:
        return plan
    return None


def _sub_summary(row) -> dict:
    return {
        "subscription_id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "plan_id": row["plan_id"],
        "status": row["status"],
    }


# ─── Cashfree webhook signature verification ──────────────────────────────────
def verify_cashfree_webhook_signature(
    timestamp: str,
    raw_body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Verify Cashfree webhook HMAC-SHA256 signature.
    signature = Base64( HMAC-SHA256(timestamp + rawBody, secretKey) )
    """
    try:
        message = (timestamp + raw_body.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        return False
    computed = base64.b64encode(
        hmac.new(secret.encode("utf-8"), message, digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature)


# ─── DB helpers ──────────────────────────────────────────────────────────────
async def create_pending_subscription(
    conn,
    user_id: str,
    plan_id: str,
    cashfree_order_id: str,
) -> str:
    """Insert a pending subscription row and return its UUID."""
    row = await conn.fetchrow(
        """
        INSERT INTO core.subscriptions
            (user_id, plan_id, status, cashfree_order_id)
        VALUES ($1, $2, 'pending', $3)
        ON CONFLICT (cashfree_order_id) DO UPDATE
            SET updated_at = NOW()
        RETURNING id
        """,
        user_id,
        plan_id,
        cashfree_order_id,
    )
    return str(row["id"])


async def activate_subscription(
    conn,
    cashfree_order_id: str,
    cashfree_payment_id: str,
    amount_paid: float,
    order_amount: Optional[float] = None,
) -> Optional[dict]:
    """
    Activate a paid order — exactly once.

    The order is claimed with a single atomic UPDATE ... WHERE status IN ('pending','failed'), so the
    webhook and /verify-order (or any repeated call) can race safely: only one caller activates and every
    other caller gets ``activated: False`` with nothing changed. Cancelled, expired, refunded, disputed
    and revoked orders can never be re-activated by calling this again.

    - The plan is only applied to the user if it does not lower a plan they currently hold.
    - Paid time is never discarded: buying any plan (the one you hold, or a higher one) while a paid
      plan is still live stacks the new duration on top of its remaining time. Buying while only a
      trial is running (no paid plan yet) stacks it on top of the trial's remaining time instead, so
      the paid period starts after the trial would have ended rather than overwriting it.
    - A live trial is ended (its history is kept) because the user is now on a paid plan.
    - ``order_amount`` (what we asked Cashfree to charge) must match the plan's price.

    Returns None if the order does not exist, otherwise a dict that includes ``activated`` (bool).
    """
    async with conn.transaction():
        existing = await conn.fetchrow(
            """
            SELECT id, user_id, plan_id, status
            FROM core.subscriptions
            WHERE cashfree_order_id = $1
            """,
            cashfree_order_id,
        )
        if not existing:
            return None

        claimed = None
        if existing["status"] in ("pending", "failed"):
            expected = PLAN_PRICES.get(existing["plan_id"])
            if order_amount is not None and expected is not None and abs(float(order_amount) - expected) > 0.5:
                return {**_sub_summary(existing), "activated": False, "reason": "amount_mismatch"}
            claimed = await conn.fetchrow(
                """
                UPDATE core.subscriptions
                SET status = 'active', cashfree_payment_id = $1, amount_paid = $2, updated_at = NOW()
                WHERE cashfree_order_id = $3 AND status IN ('pending', 'failed')
                RETURNING id, user_id, plan_id
                """,
                cashfree_payment_id,
                amount_paid,
                cashfree_order_id,
            )
        if not claimed:
            # already processed (or claimed a moment ago by a concurrent caller): change nothing
            return {**_sub_summary(existing), "activated": False, "reason": "already_processed"}

        user = await conn.fetchrow(
            "SELECT plan, plan_expires_at, trial_expires_at FROM core.users WHERE user_id = $1 FOR UPDATE",
            claimed["user_id"],
        )
        now = datetime.now(timezone.utc)
        plan_id = claimed["plan_id"]
        current = _live_paid_plan(user["plan"], user["plan_expires_at"], now) if user else None
        days = PLAN_DURATIONS.get(plan_id)

        # Stack, never discard: renewing the same plan or upgrading to a higher one while a paid plan
        # is still live extends from its current expiry, not from today. Buying while only a trial is
        # running (no paid plan yet) extends from the trial's end instead, so those days aren't wasted.
        base = now
        if days is not None and user:
            if current is not None and user["plan_expires_at"] is not None and user["plan_expires_at"] > now:
                base = user["plan_expires_at"]
            elif user["trial_expires_at"] is not None and user["trial_expires_at"] > now:
                base = user["trial_expires_at"]
        expires_at = (base + timedelta(days=days)) if days is not None else None

        await conn.execute(
            "UPDATE core.subscriptions SET starts_at = $1, expires_at = $2, updated_at = NOW() WHERE id = $3",
            now,
            expires_at,
            claimed["id"],
        )

        applied = user is not None and (current is None or PLAN_RANK[plan_id] >= PLAN_RANK[current])
        if applied:
            await conn.execute(
                """
                UPDATE core.users
                SET plan = $1,
                    plan_expires_at = $2,
                    trial_expires_at = CASE
                        WHEN trial_expires_at IS NOT NULL AND trial_expires_at > $3 THEN $3
                        ELSE trial_expires_at
                    END
                WHERE user_id = $4
                """,
                plan_id,
                expires_at,
                now,
                claimed["user_id"],
            )
        else:
            print(f"[Billing] Order {cashfree_order_id} ({plan_id}) activated but NOT applied: "
                  f"user already holds the higher plan '{current}'. Needs manual review.")

    return {
        "subscription_id": str(claimed["id"]),
        "user_id": str(claimed["user_id"]),
        "plan_id": plan_id,
        "status": "active",
        "starts_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "activated": True,
        "applied_to_user": applied,
    }

async def get_active_subscription(conn, user_id: str) -> Optional[dict]:
    """
    The user's current paid subscription, or None.
    A subscription the user cancelled keeps working until its paid period ends, so it is still
    returned (with status 'cancelled') until then.
    """
    row = await conn.fetchrow(
        """
        SELECT s.id, s.plan_id, s.status, s.starts_at, s.expires_at,
               s.cashfree_order_id, s.cashfree_payment_id, s.amount_paid,
               sp.name as plan_name, sp.price_inr, sp.features
        FROM core.subscriptions s
        JOIN core.subscription_plans sp ON sp.id = s.plan_id
        WHERE s.user_id = $1
          AND s.status IN ('active', 'cancelled')
          AND (s.expires_at IS NULL OR s.expires_at > NOW())
        ORDER BY CASE s.plan_id WHEN 'lifetime' THEN 3 WHEN 'yearly' THEN 2 WHEN 'monthly' THEN 1 ELSE 0 END DESC,
                 s.starts_at DESC
        LIMIT 1
        """,
        user_id,
    )
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["is_lifetime"] = d["expires_at"] is None
    return d


async def get_purchase_block(conn, user_id: str, target_plan: str) -> Optional[str]:
    """
    Why this user may NOT buy `target_plan` right now, or None if they may.
    Trials never block a purchase. Buying the plan you already hold renews it, and buying a higher
    plan upgrades it; only a lifetime holder, or buying a lower plan than you hold, is refused.
    """
    row = await conn.fetchrow(
        "SELECT plan, plan_expires_at FROM core.users WHERE user_id = $1",
        user_id,
    )
    if not row:
        return None
    live = _live_paid_plan(row["plan"], row["plan_expires_at"], datetime.now(timezone.utc))
    if live is None:
        return None
    if live == "lifetime":
        return "already_subscribed"
    if PLAN_RANK.get(target_plan, 0) < PLAN_RANK[live]:
        return "already_on_higher_plan"
    return None


# ─── Revocation (refunds, chargebacks, admin revoke) ─────────────────────────
async def _recompute_user_plan(conn, user_id) -> None:
    """Point users.plan at the best paid subscription still in force, or 'free' if there is none."""
    best = await conn.fetchrow(
        """
        SELECT plan_id, expires_at
        FROM core.subscriptions
        WHERE user_id = $1
          AND status IN ('active', 'cancelled')
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY CASE plan_id WHEN 'lifetime' THEN 3 WHEN 'yearly' THEN 2 WHEN 'monthly' THEN 1 ELSE 0 END DESC,
                 expires_at DESC NULLS FIRST
        LIMIT 1
        """,
        user_id,
    )
    if best:
        await conn.execute(
            "UPDATE core.users SET plan = $1, plan_expires_at = $2 WHERE user_id = $3",
            best["plan_id"], best["expires_at"], user_id,
        )
    else:
        await conn.execute(
            "UPDATE core.users SET plan = 'free', plan_expires_at = NULL WHERE user_id = $1",
            user_id,
        )


async def revoke_subscription(
    conn,
    cashfree_order_id: str,
    new_status: str,
    reason: Optional[str] = None,
    refunded_amount: Optional[float] = None,
) -> Optional[dict]:
    """
    End the access an order gave (refund / chargeback). The order can never be re-activated afterwards.
    Returns None if there was nothing to revoke (unknown order, or already refunded/revoked/expired).
    """
    if new_status not in ("refunded", "disputed", "revoked"):
        raise ValueError("new_status must be 'refunded', 'disputed' or 'revoked'")
    async with conn.transaction():
        sub = await conn.fetchrow(
            """
            UPDATE core.subscriptions
            SET status = $2,
                revoked_at = NOW(),
                revoke_reason = $3,
                refunded_amount = COALESCE($4, refunded_amount),
                updated_at = NOW()
            WHERE cashfree_order_id = $1
              AND status IN ('pending', 'failed', 'active', 'cancelled')
            RETURNING id, user_id, plan_id, status
            """,
            cashfree_order_id,
            new_status,
            reason,
            refunded_amount,
        )
        if not sub:
            return None
        await _recompute_user_plan(conn, sub["user_id"])
    return _sub_summary(sub)


async def revoke_user_subscriptions(conn, user_id, reason: str) -> int:
    """Revoke every paid subscription a user currently has (admin action). Returns how many were revoked."""
    async with conn.transaction():
        rows = await conn.fetch(
            """
            UPDATE core.subscriptions
            SET status = 'revoked', revoked_at = NOW(), revoke_reason = $2, updated_at = NOW()
            WHERE user_id = $1 AND status IN ('active', 'cancelled')
            RETURNING id
            """,
            user_id,
            reason,
        )
        await _recompute_user_plan(conn, user_id)
    return len(rows)

# ─── Global Launch Trial & User Trial Management ──────────────────────────────
async def get_launch_config(conn) -> dict:
    """Fetch current launch trial config."""
    row = await conn.fetchrow(
        """
        SELECT id, is_active, trial_days, trial_start, trial_end,
               new_user_trial_days, coupon_grace_days, created_at, updated_at
        FROM core.launch_config
        WHERE id = 1
        """
    )
    if not row:
        return {
            "is_active": False,
            "trial_days": 30,
            "trial_start": None,
            "trial_end": None,
            "new_user_trial_days": 7,
            "coupon_grace_days": 2,
        }
    return dict(row)


async def set_launch_config(
    conn,
    is_active: bool,
    trial_days: int = 30,
    new_user_trial_days: int = 7,
    coupon_grace_days: int = 2,
) -> dict:
    """
    Set or toggle the global launch trial.

    - Turning it ON starts a new window (trial_start = now) and gives every free user who has not
      used a personal signup trial a global trial that ends with the window.
    - Saving again while the window is already running does NOT restart it or hand out trials again.
      Changing ``trial_days`` then extends/shortens the running window, and live global trials follow it.
    - Turning it OFF ends every live global trial immediately. Personal 7-day signup trials that were
      already granted are honoured until they end.
    """
    now = datetime.now(timezone.utc)
    async with conn.transaction():
        current = await get_launch_config(conn)
        cur_start, cur_end = current.get("trial_start"), current.get("trial_end")
        window_running = bool(current.get("is_active") and cur_start and cur_end and now < cur_end)

        if is_active and window_running:
            new_end = cur_start + timedelta(days=trial_days)
            await conn.execute(
                """
                UPDATE core.launch_config
                SET trial_days = $1, trial_end = $2, new_user_trial_days = $3,
                    coupon_grace_days = $4, updated_at = NOW()
                WHERE id = 1
                """,
                trial_days, new_end, new_user_trial_days, coupon_grace_days,
            )
            if new_end != cur_end:
                await conn.execute(
                    """
                    UPDATE core.users SET trial_expires_at = $1
                    WHERE trial_type = 'global_trial' AND trial_expires_at > $2
                    """,
                    new_end, now,
                )
        elif is_active:
            trial_end = now + timedelta(days=trial_days)
            await conn.execute(
                """
                INSERT INTO core.launch_config
                    (id, is_active, trial_days, trial_start, trial_end, new_user_trial_days, coupon_grace_days, updated_at)
                VALUES (1, TRUE, $1, $2, $3, $4, $5, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    is_active = TRUE,
                    trial_days = EXCLUDED.trial_days,
                    trial_start = EXCLUDED.trial_start,
                    trial_end = EXCLUDED.trial_end,
                    new_user_trial_days = EXCLUDED.new_user_trial_days,
                    coupon_grace_days = EXCLUDED.coupon_grace_days,
                    updated_at = NOW()
                """,
                trial_days, now, trial_end, new_user_trial_days, coupon_grace_days,
            )
            await conn.execute(
                """
                UPDATE core.users
                SET trial_expires_at = $1, trial_type = 'global_trial'
                WHERE plan = 'free' AND (trial_type IS NULL OR trial_type = 'global_trial')
                """,
                trial_end,
            )
        else:
            await conn.execute(
                """
                INSERT INTO core.launch_config
                    (id, is_active, trial_days, new_user_trial_days, coupon_grace_days, updated_at)
                VALUES (1, FALSE, $1, $2, $3, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    is_active = FALSE,
                    trial_days = EXCLUDED.trial_days,
                    new_user_trial_days = EXCLUDED.new_user_trial_days,
                    coupon_grace_days = EXCLUDED.coupon_grace_days,
                    updated_at = NOW()
                """,
                trial_days, new_user_trial_days, coupon_grace_days,
            )
            await conn.execute(
                """
                UPDATE core.users SET trial_expires_at = $1
                WHERE trial_type = 'global_trial' AND trial_expires_at > $1
                """,
                now,
            )

    return await get_launch_config(conn)

async def apply_new_user_trial(conn, user_id: str) -> bool:
    """
    Called on new user signup (email or Google OAuth).
    If the global launch trial is active, gives the new user a signup trial — but only once per mailbox:
    aliases such as a+1@gmail.com or a.b@gmail.com count as the same mailbox as a@gmail.com.
    """
    cfg = await get_launch_config(conn)
    if not cfg.get("is_active"):
        return False

    now = datetime.now(timezone.utc)
    trial_end = cfg.get("trial_end")
    if not trial_end or now > trial_end:
        return False

    try:
        already_used = await conn.fetchval(
            """
            SELECT 1
            FROM core.users me
            JOIN core.users other
              ON other.user_id <> me.user_id
             AND core.canonical_email(other.email) = core.canonical_email(me.email)
            WHERE me.user_id = $1
              AND other.trial_type IS NOT NULL
            LIMIT 1
            """,
            user_id,
        )
    except Exception as exc:  # migration not applied yet: never break sign-up over this check
        print(f"[Trial] mailbox check skipped (run billing_hardening.sql): {exc}")
        already_used = None
    if already_used:
        return False

    days = cfg.get("new_user_trial_days", 7)
    user_trial_expires = now + timedelta(days=days)

    await conn.execute(
        """
        UPDATE core.users
        SET trial_expires_at = $1, trial_type = 'new_signup'
        WHERE user_id = $2 AND plan = 'free'
        """,
        user_trial_expires,
        user_id,
    )
    return True

# ─── Access Control Hierarchy ─────────────────────────────────────────────────
def _eligible_for_global_trial(row, cfg: dict, now: datetime) -> bool:
    """
    The global launch window covers only users who already existed when it opened and who hold no
    personal trial record. Anyone who signed up during the window (or already used a trial) is decided
    by their own trial record, never by the window.
    """
    start, end = cfg.get("trial_start"), cfg.get("trial_end")
    if not (cfg.get("is_active") and start and end and start <= now <= end):
        return False
    if row["trial_type"] is not None or row["trial_expires_at"] is not None:
        return False
    created = row["created_at"]
    return created is not None and created <= start


async def has_active_subscription(conn, user_id: str) -> bool:
    """
    Unified access check. A user has full access if:
      1. they hold a paid plan that is in force (lifetime, or monthly/yearly not yet expired), or
      2. they have a personal trial that has not ended (an ended trial stays ended), or
      3. the global launch window is running and they are an existing user with no personal trial record.
    Otherwise False (free tier: first 30 SQL questions + today's free SQL daily set).
    """
    row = await conn.fetchrow(
        """
        SELECT plan, plan_expires_at, trial_expires_at, trial_type, created_at
        FROM core.users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not row:
        return False

    now = datetime.now(timezone.utc)
    if _live_paid_plan(row["plan"] or "free", row["plan_expires_at"], now):
        return True
    if row["trial_expires_at"] is not None:
        return row["trial_expires_at"] > now
    return _eligible_for_global_trial(row, await get_launch_config(conn), now)

async def get_user_full_access_status(conn, user_id: str) -> dict:
    """Detailed access status for profile, trial banners, and UI countdown."""
    row = await conn.fetchrow(
        """
        SELECT plan, plan_expires_at, trial_expires_at, trial_type, email, full_name, created_at
        FROM core.users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not row:
        return {
            "has_access": False,
            "plan": "free",
            "is_paid": False,
            "is_trial": False,
            "trial_type": None,
            "trial_expires_at": None,
            "trial_days_remaining": 0,
            "trial_hours_remaining": 0,
            "trial_expired": False,
            "plan_expires_at": None,
            "is_lifetime": False,
        }

    now = datetime.now(timezone.utc)
    plan = row["plan"] or "free"
    is_paid = _live_paid_plan(plan, row["plan_expires_at"], now) is not None

    cfg = await get_launch_config(conn)
    is_user_trial = bool(row["trial_expires_at"] and row["trial_expires_at"] > now)
    is_user_trial_expired = bool(row["trial_expires_at"] and row["trial_expires_at"] <= now)
    eligible_for_global = _eligible_for_global_trial(row, cfg, now)

    is_trial = (not is_paid) and (is_user_trial or eligible_for_global)
    trial_type = row["trial_type"] or ("global_trial" if eligible_for_global else None)

    effective_trial_expiry = row["trial_expires_at"]
    if not effective_trial_expiry and eligible_for_global:
        effective_trial_expiry = cfg.get("trial_end")

    trial_days_remaining = 0
    trial_hours_remaining = 0
    if is_trial and effective_trial_expiry:
        diff = effective_trial_expiry - now
        trial_days_remaining = max(0, diff.days + (1 if diff.seconds > 0 else 0))
        trial_hours_remaining = max(0, int(diff.total_seconds() // 3600))

    trial_expired = (not is_paid) and (is_user_trial_expired or (row["trial_type"] is not None and not is_trial))
    has_access = is_paid or is_trial

    return {
        "has_access": has_access,
        "plan": plan,
        "is_paid": is_paid,
        "is_trial": is_trial,
        "trial_type": trial_type,
        "trial_expires_at": effective_trial_expiry.isoformat() if effective_trial_expiry else None,
        "trial_days_remaining": trial_days_remaining,
        "trial_hours_remaining": trial_hours_remaining,
        "trial_expired": trial_expired,
        "plan_expires_at": row["plan_expires_at"].isoformat() if row["plan_expires_at"] else None,
        "is_lifetime": plan == "lifetime",
    }

# ─── Coupon Code System ───────────────────────────────────────────────────────
def generate_coupon_code() -> str:
    """Generate cryptographically random uppercase code: DSQL-LT-XXXXXXXX."""
    alphabet = string.ascii_uppercase + string.digits
    # Exclude confusing chars like 0, O, 1, I
    clean_alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    suffix = "".join(secrets.choice(clean_alphabet) for _ in range(8))
    return f"DSQL-LT-{suffix}"


async def generate_coupons_for_users(
    conn,
    users: List[Dict[str, Any]],
    expires_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Generate unique coupon codes for a list of users/emails.
    Each coupon is strictly bound to user's email.
    If an unused coupon already exists for an email, its expiry is refreshed to expires_at.
    """
    import uuid as py_uuid
    results = []
    now = datetime.now(timezone.utc)

    for u in users:
        email = u.get("email", "").lower().strip()
        if not email:
            continue

        user_id_raw = u.get("user_id")
        user_id_val = None
        if user_id_raw:
            try:
                user_id_val = py_uuid.UUID(str(user_id_raw))
            except Exception:
                user_id_val = None

        # Check if unused coupon already exists for this email
        existing = await conn.fetchrow(
            """
            SELECT code, email, expires_at, is_used, used_at, created_at
            FROM core.coupons
            WHERE LOWER(email) = $1 AND is_used = FALSE
            """,
            email,
        )
        if existing:
            code = existing["code"]
            is_used = existing["is_used"]
            used_at = existing["used_at"]
            created_at = existing["created_at"]
            # Refresh expiry to the new value requested by admin
            exp = expires_at if expires_at is not None else existing["expires_at"]
            if expires_at is not None:
                await conn.execute(
                    "UPDATE core.coupons SET expires_at = $1 WHERE code = $2",
                    expires_at,
                    code,
                )
        else:
            code = generate_coupon_code()
            exp = expires_at
            is_used = False
            used_at = None
            created_at = now

            await conn.execute(
                """
                INSERT INTO core.coupons (code, email, user_id, plan_granted, is_used, expires_at, created_at)
                VALUES ($1, $2, $3::uuid, 'lifetime', FALSE, $4, NOW())
                ON CONFLICT (code) DO UPDATE SET expires_at = EXCLUDED.expires_at
                """,
                code,
                email,
                user_id_val,
                exp,
            )

        status = "Redeemed" if is_used else ("Expired" if (exp and exp < now) else "Active")

        results.append({
            "email": email,
            "username": u.get("username"),
            "full_name": u.get("full_name"),
            "coupon_code": code,
            "code": code,
            "plan_granted": "lifetime",
            "is_used": is_used,
            "status": status,
            "used_at": used_at.isoformat() if used_at else None,
            "expires_at": exp.isoformat() if exp else None,
            "created_at": created_at.isoformat() if created_at else now.isoformat(),
        })

    return results


async def redeem_coupon(conn, user_id: str, user_email: str, code: str) -> dict:
    """
    Redeem a coupon code, atomically:
      1. Must exist.
      2. Must not be used.
      3. Must not be expired.
      4. Must match the user's email.
    Everything happens in ONE transaction with the coupon row locked, so a coupon can never be
    burned without granting access, and two simultaneous redemptions cannot both succeed.
    """
    clean_code = code.strip().upper()
    clean_email = user_email.lower().strip()

    async with conn.transaction():
        coupon = await conn.fetchrow(
            """
            SELECT code, email, user_id, plan_granted, is_used, expires_at
            FROM core.coupons
            WHERE code = $1
            FOR UPDATE
            """,
            clean_code,
        )

        if not coupon:
            raise ValueError("Invalid coupon code.")

        if coupon["is_used"]:
            raise ValueError("This coupon code has already been redeemed.")

        now = datetime.now(timezone.utc)
        if coupon["expires_at"] and coupon["expires_at"] < now:
            raise ValueError("This coupon code has expired.")

        # Strict ownership check: coupon must be registered to this specific email
        if coupon["email"].lower().strip() != clean_email:
            raise ValueError("This coupon code was issued to a different email address.")

        if not await conn.fetchval("SELECT 1 FROM core.users WHERE user_id = $1", user_id):
            raise ValueError("We could not find your account to apply this coupon. Please contact support.")

        plan_granted = coupon["plan_granted"] or "lifetime"
        if plan_granted not in PLAN_DURATIONS:
            raise ValueError("This coupon grants an unsupported plan. Please contact support.")
        days = PLAN_DURATIONS[plan_granted]
        expires_at = (now + timedelta(days=days)) if days is not None else None

        marked = await conn.execute(
            """
            UPDATE core.coupons
            SET is_used = TRUE, used_by = $1, used_at = NOW()
            WHERE code = $2 AND is_used = FALSE
            """,
            user_id,
            clean_code,
        )
        if marked != "UPDATE 1":
            raise ValueError("This coupon code has already been redeemed.")

        granted = await conn.execute(
            """
            UPDATE core.users
            SET plan = $1,
                plan_expires_at = $2,
                trial_expires_at = CASE
                    WHEN trial_expires_at IS NOT NULL AND trial_expires_at > $3 THEN $3
                    ELSE trial_expires_at
                END
            WHERE user_id = $4
            """,
            plan_granted,
            expires_at,
            now,
            user_id,
        )
        if granted != "UPDATE 1":
            # raising here rolls the whole transaction back, so the coupon is NOT burned
            raise ValueError("We could not find your account to apply this coupon. Please contact support.")

        await conn.execute(
            """
            INSERT INTO core.subscriptions
                (user_id, plan_id, status, cashfree_order_id, cashfree_payment_id, amount_paid, starts_at, expires_at)
            VALUES ($1, $2, 'active', $3, 'COUPON_REDEEMED', 0.00, NOW(), $4)
            ON CONFLICT (cashfree_order_id) DO NOTHING
            """,
            user_id,
            plan_granted,
            f"COUPON_{clean_code}",
            expires_at,
        )

    return {
        "success": True,
        "code": clean_code,
        "plan_granted": plan_granted,
        "message": "Coupon successfully redeemed! You now have permanent Lifetime access.",
    }

# ─── Stale Subscriptions & Trials Expiry ──────────────────────────────────────
async def expire_stale_subscriptions(conn) -> None:
    """Sweep expired subscriptions and trials. Call on startup."""
    await conn.execute("SELECT core.expire_stale_subscriptions()")
