-- ============================================================
-- Migration: Subscription, Trial & Coupon System
-- ============================================================

-- 1. Add plan and trial columns to core.users
ALTER TABLE core.users
    ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free'
        CHECK (plan IN ('free', 'monthly', 'yearly', 'lifetime')),
    ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS trial_type TEXT;

-- 2. Add row_number to problems for free-tier gating (first 30)
ALTER TABLE core.problems
    ADD COLUMN IF NOT EXISTS row_number SERIAL;

WITH numbered AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC, id ASC) AS rn
    FROM core.problems
    WHERE challenge_type = 'sql'
)
UPDATE core.problems p
SET row_number = n.rn
FROM numbered n
WHERE p.id = n.id;

-- 3. Subscription plans catalogue
CREATE TABLE IF NOT EXISTS core.subscription_plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_inr NUMERIC(10,2) NOT NULL,
    duration_days INTEGER,          -- NULL = lifetime
    features JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO core.subscription_plans (id, name, price_inr, duration_days, features)
VALUES
    ('monthly',  'Monthly Plan',  899.00,  30,   '["Full access to all questions", "All challenge types", "Priority support"]'::jsonb),
    ('yearly',   'Yearly Plan',   1499.00, 365,  '["Full access to all questions", "All challenge types", "Priority support", "Best value"]'::jsonb),
    ('lifetime', 'Lifetime Plan', 4999.00, NULL, '["Full access to all questions", "All challenge types", "VIP support", "All future content"]'::jsonb)
ON CONFLICT (id) DO NOTHING;  -- never overwrite prices edited from the CMS

-- 4. Subscriptions table
CREATE TABLE IF NOT EXISTS core.subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL REFERENCES core.subscription_plans(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'expired', 'cancelled', 'failed')),
    cashfree_order_id TEXT UNIQUE NOT NULL,
    cashfree_payment_id TEXT,
    amount_paid NUMERIC(10,2),
    starts_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,     -- NULL = lifetime
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS subscriptions_user_id_status_idx
    ON core.subscriptions (user_id, status);

CREATE INDEX IF NOT EXISTS subscriptions_cashfree_order_id_idx
    ON core.subscriptions (cashfree_order_id);

-- 5. Launch Trial Configuration table
CREATE TABLE IF NOT EXISTS core.launch_config (
    id SERIAL PRIMARY KEY,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    trial_days INTEGER NOT NULL DEFAULT 30,
    trial_start TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    new_user_trial_days INTEGER NOT NULL DEFAULT 7,
    coupon_grace_days INTEGER NOT NULL DEFAULT 2, -- trial + 2 days
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO core.launch_config (id, is_active, trial_days, new_user_trial_days, coupon_grace_days)
VALUES (1, FALSE, 30, 7, 2)
ON CONFLICT (id) DO NOTHING;

-- 6. Coupons table (bound to specific user email, single-use, lifetime access)
CREATE TABLE IF NOT EXISTS core.coupons (
    code TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    user_id UUID REFERENCES core.users(user_id) ON DELETE SET NULL,
    plan_granted TEXT NOT NULL DEFAULT 'lifetime',
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    used_by UUID REFERENCES core.users(user_id) ON DELETE SET NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS coupons_email_idx ON core.coupons (LOWER(email));
CREATE INDEX IF NOT EXISTS coupons_is_used_idx ON core.coupons (is_used);

-- 7. Auto-expire subscriptions and trials function
-- NOTE: superseded by backend/app/billing_hardening.sql (cancelled plans keep access until the
-- paid period ends; trial history is kept). Run that file after this one.
