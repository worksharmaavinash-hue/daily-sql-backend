-- ============================================================================
-- Billing hardening (idempotent — safe to run any number of times)
-- Applied automatically by create_tables.py, or manually:
--   docker exec -i <postgres-container> psql -U <user> -d <db> < backend/app/billing_hardening.sql
-- ============================================================================

-- 1. Subscription status values: add refunded / disputed / revoked ------------
DO $$
DECLARE c RECORD;
BEGIN
    FOR c IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'core.subscriptions'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%status%'
    LOOP
        EXECUTE format('ALTER TABLE core.subscriptions DROP CONSTRAINT %I', c.conname);
    END LOOP;

    ALTER TABLE core.subscriptions
        ADD CONSTRAINT subscriptions_status_check
        CHECK (status IN ('pending', 'active', 'expired', 'cancelled', 'failed',
                          'refunded', 'disputed', 'revoked'));
END $$;

-- 2. Audit columns -------------------------------------------------------------
ALTER TABLE core.subscriptions ADD COLUMN IF NOT EXISTS refunded_amount NUMERIC(10,2);
ALTER TABLE core.subscriptions ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE core.subscriptions ADD COLUMN IF NOT EXISTS revoke_reason TEXT;
ALTER TABLE core.subscriptions ADD COLUMN IF NOT EXISTS granted_by TEXT;

-- 3. One mailbox = one trial ---------------------------------------------------
-- Canonical form of an email address: lower-cased, "+tag" removed, and for Gmail also dots
-- removed (a.b+x@gmail.com == ab@gmail.com). Used only to stop trial farming via aliases.
CREATE OR REPLACE FUNCTION core.canonical_email(e TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE
        WHEN split_part(lower(e), '@', 2) IN ('gmail.com', 'googlemail.com')
            THEN replace(split_part(split_part(lower(e), '@', 1), '+', 1), '.', '') || '@gmail.com'
        ELSE split_part(split_part(lower(e), '@', 1), '+', 1) || '@' || split_part(lower(e), '@', 2)
    END
$fn$;

CREATE INDEX IF NOT EXISTS users_canonical_email_idx ON core.users (core.canonical_email(email));

-- 4. Expiry sweep ----------------------------------------------------------------
--  * cancelled subscriptions keep access until their paid period really ends
--  * trial history (trial_type / trial_expires_at) is KEPT so an expired trial can never
--    silently turn back into access
CREATE OR REPLACE FUNCTION core.expire_stale_subscriptions()
RETURNS void AS $fn$
BEGIN
    UPDATE core.subscriptions
    SET status = 'expired', updated_at = NOW()
    WHERE status IN ('active', 'cancelled')
      AND expires_at IS NOT NULL
      AND expires_at < NOW();

    UPDATE core.users u
    SET plan = 'free', plan_expires_at = NULL
    WHERE u.plan IN ('monthly', 'yearly')
      AND u.plan_expires_at IS NOT NULL
      AND u.plan_expires_at < NOW()
      AND NOT EXISTS (
          SELECT 1 FROM core.subscriptions s
          WHERE s.user_id = u.user_id
            AND s.status IN ('active', 'cancelled')
            AND (s.expires_at IS NULL OR s.expires_at > NOW())
      );
END;
$fn$ LANGUAGE plpgsql;
