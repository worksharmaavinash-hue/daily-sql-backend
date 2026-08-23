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
    message = (timestamp + raw_body.decode("utf-8")).encode("utf-8")
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
) -> Optional[dict]:
    """
    Activate a pending subscription by its Cashfree order ID.
    Updates the subscription row and core.users.plan / plan_expires_at.
    Returns the subscription dict, or None if order not found.
    """
    sub = await conn.fetchrow(
        """
        SELECT id, user_id, plan_id
        FROM core.subscriptions
        WHERE cashfree_order_id = $1
        """,
        cashfree_order_id,
    )
    if not sub:
        return None

    plan_id = sub["plan_id"]
    user_id = sub["user_id"]
    starts_at = datetime.now(timezone.utc)
    expires_at = _compute_expires_at(plan_id)

    # Activate the subscription row
    await conn.execute(
        """
        UPDATE core.subscriptions
        SET
            status              = 'active',
            cashfree_payment_id = $1,
            amount_paid         = $2,
            starts_at           = $3,
            expires_at          = $4,
            updated_at          = NOW()
        WHERE cashfree_order_id = $5
        """,
        cashfree_payment_id,
        amount_paid,
        starts_at,
        expires_at,
        cashfree_order_id,
    )

    # Update the user's plan on the users table for fast lookups
    await conn.execute(
        """
        UPDATE core.users
        SET plan = $1, plan_expires_at = $2, trial_expires_at = NULL, trial_type = NULL
        WHERE user_id = $3
        """,
        plan_id,
        expires_at,
        user_id,
    )

    return {
        "subscription_id": str(sub["id"]),
        "user_id": str(user_id),
        "plan_id": plan_id,
        "starts_at": starts_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


async def get_active_subscription(conn, user_id: str) -> Optional[dict]:
    """Return the user's current active subscription or None."""
    row = await conn.fetchrow(
        """
        SELECT s.id, s.plan_id, s.status, s.starts_at, s.expires_at,
               s.cashfree_order_id, s.cashfree_payment_id, s.amount_paid,
               sp.name as plan_name, sp.price_inr, sp.features
        FROM core.subscriptions s
        JOIN core.subscription_plans sp ON sp.id = s.plan_id
        WHERE s.user_id = $1
          AND s.status = 'active'
        ORDER BY s.starts_at DESC
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
    When activated:
      - Sets trial_start = NOW() and trial_end = NOW() + trial_days
      - Sets trial_expires_at for all existing free users
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=trial_days) if is_active else None
    trial_start = now if is_active else None

    await conn.execute(
        """
        INSERT INTO core.launch_config (id, is_active, trial_days, trial_start, trial_end, new_user_trial_days, coupon_grace_days, updated_at)
        VALUES (1, $1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (id) DO UPDATE SET
            is_active = EXCLUDED.is_active,
            trial_days = EXCLUDED.trial_days,
            trial_start = COALESCE(EXCLUDED.trial_start, core.launch_config.trial_start),
            trial_end = COALESCE(EXCLUDED.trial_end, core.launch_config.trial_end),
            new_user_trial_days = EXCLUDED.new_user_trial_days,
            coupon_grace_days = EXCLUDED.coupon_grace_days,
            updated_at = NOW()
        """,
        is_active,
        trial_days,
        trial_start,
        trial_end,
        new_user_trial_days,
        coupon_grace_days,
    )

    # When activating launch trial, apply it to all current free users
    if is_active and trial_end:
        await conn.execute(
            """
            UPDATE core.users
            SET trial_expires_at = $1, trial_type = 'global_trial'
            WHERE plan = 'free'
            """,
            trial_end,
        )

    return await get_launch_config(conn)


async def apply_new_user_trial(conn, user_id: str) -> bool:
    """
    Called on new user signup (email or Google OAuth).
    If global launch trial is active, gives new user a 7-day trial.
    """
    cfg = await get_launch_config(conn)
    if not cfg.get("is_active"):
        return False

    now = datetime.now(timezone.utc)
    trial_end = cfg.get("trial_end")
    if not trial_end or now > trial_end:
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
async def has_active_subscription(conn, user_id: str) -> bool:
    """
    Unified access check. User gets full access if:
      1. Has active paid plan (lifetime, or valid monthly/yearly).
      2. Has an active user trial (trial_expires_at > NOW()).
      3. Global launch trial is currently active (launch_config.trial_start <= NOW() <= launch_config.trial_end).
    Otherwise False (free tier access: first 30 SQL questions + daily set).
    """
    row = await conn.fetchrow(
        """
        SELECT plan, plan_expires_at, trial_expires_at, created_at
        FROM core.users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not row:
        return False

    now = datetime.now(timezone.utc)
    plan = row["plan"] or "free"

    # 1. Paid plan
    if plan == "lifetime":
        return True
    if plan in ("monthly", "yearly") and row["plan_expires_at"] and row["plan_expires_at"] > now:
        return True

    # 2. User specific trial
    if row["trial_expires_at"] and row["trial_expires_at"] > now:
        return True

    # 3. Dynamic check for global launch trial window
    cfg = await get_launch_config(conn)
    if cfg.get("is_active") and cfg.get("trial_start") and cfg.get("trial_end"):
        if cfg["trial_start"] <= now <= cfg["trial_end"]:
            return True

    return False


async def get_user_full_access_status(conn, user_id: str) -> dict:
    """Detailed access status for profile and UI banners."""
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
            "plan_expires_at": None,
        }

    now = datetime.now(timezone.utc)
    plan = row["plan"] or "free"
    is_paid = (
        plan == "lifetime"
        or (plan in ("monthly", "yearly") and row["plan_expires_at"] and row["plan_expires_at"] > now)
    )

    is_user_trial = bool(row["trial_expires_at"] and row["trial_expires_at"] > now)

    # Check global trial
    cfg = await get_launch_config(conn)
    is_global_trial = bool(
        cfg.get("is_active")
        and cfg.get("trial_start")
        and cfg.get("trial_end")
        and cfg["trial_start"] <= now <= cfg["trial_end"]
    )

    is_trial = not is_paid and (is_user_trial or is_global_trial)
    trial_type = row["trial_type"] or ("global_trial" if is_global_trial else None)

    effective_trial_expiry = row["trial_expires_at"]
    if not effective_trial_expiry and is_global_trial:
        effective_trial_expiry = cfg.get("trial_end")

    has_access = is_paid or is_trial

    return {
        "has_access": has_access,
        "plan": plan,
        "is_paid": is_paid,
        "is_trial": is_trial,
        "trial_type": trial_type,
        "trial_expires_at": effective_trial_expiry.isoformat() if effective_trial_expiry else None,
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
    """
    results = []
    for u in users:
        email = u.get("email", "").lower().strip()
        if not email:
            continue
        user_id = u.get("user_id")

        # Check if unused coupon already exists for this email
        existing = await conn.fetchrow(
            """
            SELECT code, email, expires_at, is_used
            FROM core.coupons
            WHERE LOWER(email) = $1 AND is_used = FALSE
            """,
            email,
        )
        if existing:
            code = existing["code"]
            exp = existing["expires_at"]
        else:
            code = generate_coupon_code()
            exp = expires_at

            await conn.execute(
                """
                INSERT INTO core.coupons (code, email, user_id, plan_granted, is_used, expires_at)
                VALUES ($1, $2, $3, 'lifetime', FALSE, $4)
                ON CONFLICT (code) DO NOTHING
                """,
                code,
                email,
                user_id,
                exp,
            )

        results.append({
            "email": email,
            "username": u.get("username"),
            "full_name": u.get("full_name"),
            "coupon_code": code,
            "expires_at": exp.isoformat() if exp else None,
        })

    return results


async def redeem_coupon(conn, user_id: str, user_email: str, code: str) -> dict:
    """
    Redeem a coupon code:
      1. Must exist.
      2. Must not be used.
      3. Must not be expired.
      4. Must match user's email.
    Grants lifetime access immediately.
    """
    clean_code = code.strip().upper()
    clean_email = user_email.lower().strip()

    coupon = await conn.fetchrow(
        """
        SELECT code, email, user_id, plan_granted, is_used, expires_at
        FROM core.coupons
        WHERE code = $1
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

    plan_granted = coupon["plan_granted"] or "lifetime"

    # Transactional redemption
    await conn.execute(
        """
        UPDATE core.coupons
        SET is_used = TRUE, used_by = $1, used_at = NOW()
        WHERE code = $2
        """,
        user_id,
        clean_code,
    )

    # Update user plan
    await conn.execute(
        """
        UPDATE core.users
        SET plan = $1, plan_expires_at = NULL, trial_expires_at = NULL, trial_type = NULL
        WHERE user_id = $2
        """,
        plan_granted,
        user_id,
    )

    # Insert active subscription record
    await conn.execute(
        """
        INSERT INTO core.subscriptions
            (user_id, plan_id, status, cashfree_order_id, cashfree_payment_id, amount_paid, starts_at, expires_at)
        VALUES ($1, $2, 'active', $3, 'COUPON_REDEEMED', 0.00, NOW(), NULL)
        ON CONFLICT (cashfree_order_id) DO NOTHING
        """,
        user_id,
        plan_granted,
        f"COUPON_{clean_code}",
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
