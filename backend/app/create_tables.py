import asyncio
import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/dailysql")

async def init_db():
    print(f"Connecting to {DATABASE_URL}...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print("Connected.")
        
        with open("app/schema.sql", "r") as f:
            schema_sql = f.read()
            
        print("Creating schema...")
        await conn.execute(schema_sql)
        print("Schema created successfully.")

        print("Applying dynamic schema migrations...")
        try:
            await conn.execute("""
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS hashed_password TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS auth_provider TEXT DEFAULT 'email';
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS provider_id TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS avatar_url TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS is_public_profile BOOLEAN DEFAULT TRUE;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS bio TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS linkedin_url TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS github_url TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS profile_updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS whatsapp_number TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS source TEXT;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE;
                ALTER TABLE core.problem_datasets ADD COLUMN IF NOT EXISTS column_types JSONB NOT NULL DEFAULT '{}'::jsonb;
                
                -- NEW PYTHON/PYSPARK MIGRATIONS
                ALTER TABLE core.problems ADD COLUMN IF NOT EXISTS challenge_type TEXT NOT NULL DEFAULT 'sql';
                ALTER TABLE core.problems DROP CONSTRAINT IF EXISTS problems_challenge_type_check;
                ALTER TABLE core.problems ADD CONSTRAINT problems_challenge_type_check CHECK (challenge_type IN ('sql', 'python', 'pyspark', 'python_dsa'));
                
                ALTER TABLE core.problem_datasets ADD COLUMN IF NOT EXISTS seed_data_json JSONB;
                ALTER TABLE core.problem_solutions ALTER COLUMN reference_query DROP NOT NULL;
                ALTER TABLE core.problem_solutions ADD COLUMN IF NOT EXISTS reference_code TEXT;
                ALTER TABLE core.problem_solutions ADD COLUMN IF NOT EXISTS reference_output JSONB;
                ALTER TABLE core.problem_solutions ADD COLUMN IF NOT EXISTS function_name TEXT;
                ALTER TABLE core.problem_solutions ADD COLUMN IF NOT EXISTS starter_code TEXT;
                ALTER TABLE core.attempts ADD COLUMN IF NOT EXISTS challenge_type TEXT DEFAULT 'sql';
                
                -- NEW DAILY PRACTICE EXPANSION COLUMNS
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS python_easy_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS python_medium_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS python_advanced_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS pyspark_easy_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS pyspark_medium_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS pyspark_advanced_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS dsa_easy_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS dsa_medium_problem_id UUID REFERENCES core.problems(id);
                ALTER TABLE core.daily_practice ADD COLUMN IF NOT EXISTS dsa_advanced_problem_id UUID REFERENCES core.problems(id);

                CREATE TABLE IF NOT EXISTS core.whitelist (
                    email TEXT PRIMARY KEY,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS core.waitlist (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email TEXT UNIQUE NOT NULL,
                    whatsapp_number TEXT,
                    full_name TEXT NOT NULL,
                    occupation TEXT,
                    job_role TEXT,
                    experience_years INTEGER,
                    source TEXT,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                -- Create WhatsApp group members tracking table
                CREATE TABLE IF NOT EXISTS core.wa_group_members (
                    user_id   UUID PRIMARY KEY REFERENCES core.users(user_id) ON DELETE CASCADE,
                    added_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS core.problem_test_cases (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    problem_id  UUID NOT NULL REFERENCES core.problems(id) ON DELETE CASCADE,
                    input_data  JSONB NOT NULL,
                    expected    JSONB NOT NULL,
                    is_hidden   BOOLEAN DEFAULT TRUE,
                    label       TEXT,
                    order_index INT DEFAULT 0,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS problem_test_cases_problem_id_idx ON core.problem_test_cases(problem_id);

                CREATE TABLE IF NOT EXISTS core.comment_votes (
                    user_id    UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
                    comment_id UUID NOT NULL REFERENCES core.comments(id) ON DELETE CASCADE,
                    vote_type  SMALLINT NOT NULL CHECK (vote_type IN (1, -1)),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (user_id, comment_id)
                );

                -- MYSQL DIALECT SUPPORT
                ALTER TABLE core.problem_datasets ADD COLUMN IF NOT EXISTS mysql_schema_sql TEXT;
                ALTER TABLE core.problem_datasets ADD COLUMN IF NOT EXISTS mysql_seed_sql TEXT;
                ALTER TABLE core.problem_solutions ADD COLUMN IF NOT EXISTS mysql_reference_query TEXT;

                -- SUBSCRIPTION SYSTEM
                -- 1. Add row_number to problems for free-tier gating
                ALTER TABLE core.problems ADD COLUMN IF NOT EXISTS row_number SERIAL;

                -- 2. Add plan columns to users
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free';
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMP WITH TIME ZONE;

                -- 3. Subscription plans catalogue
                CREATE TABLE IF NOT EXISTS core.subscription_plans (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_inr NUMERIC(10,2) NOT NULL,
                    duration_days INTEGER,
                    features JSONB NOT NULL DEFAULT '[]'::jsonb,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

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
                    expires_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS subscriptions_user_id_status_idx ON core.subscriptions (user_id, status);
                CREATE INDEX IF NOT EXISTS subscriptions_cashfree_order_id_idx ON core.subscriptions (cashfree_order_id);

                -- 5. Launch Trial Configuration table
                CREATE TABLE IF NOT EXISTS core.launch_config (
                    id SERIAL PRIMARY KEY,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    trial_days INTEGER NOT NULL DEFAULT 30,
                    trial_start TIMESTAMP WITH TIME ZONE,
                    trial_end TIMESTAMP WITH TIME ZONE,
                    new_user_trial_days INTEGER NOT NULL DEFAULT 7,
                    coupon_grace_days INTEGER NOT NULL DEFAULT 2,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

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

                -- 7. Add trial columns to users
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP WITH TIME ZONE;
                ALTER TABLE core.users ADD COLUMN IF NOT EXISTS trial_type TEXT;

                -- 8. Stale subscription and trial expiry function
                CREATE OR REPLACE FUNCTION core.expire_stale_subscriptions()
                RETURNS void AS $fn$
                BEGIN
                    UPDATE core.subscriptions
                    SET status = 'expired', updated_at = NOW()
                    WHERE status = 'active'
                      AND expires_at IS NOT NULL
                      AND expires_at < NOW();

                    UPDATE core.users u
                    SET plan = 'free', plan_expires_at = NULL
                    WHERE plan != 'free'
                      AND plan != 'lifetime'
                      AND NOT EXISTS (
                          SELECT 1 FROM core.subscriptions s
                          WHERE s.user_id = u.user_id
                            AND s.status = 'active'
                      );

                    UPDATE core.users
                    SET trial_expires_at = NULL, trial_type = NULL
                    WHERE trial_expires_at IS NOT NULL
                      AND trial_expires_at < NOW();
                END;
                $fn$ LANGUAGE plpgsql;

            """)
            print("Migrations applied successfully.")

            # Seed subscription plans and initial launch config
            try:
                conn_seed = await asyncpg.connect(DATABASE_URL)
                await conn_seed.execute("""
                    INSERT INTO core.subscription_plans (id, name, price_inr, duration_days, features)
                    VALUES
                        ('monthly',  'Monthly Plan',  899.00,  30,   '["Full access to all questions", "All challenge types", "Priority support"]'::jsonb),
                        ('yearly',   'Yearly Plan',   1499.00, 365,  '["Full access to all questions", "All challenge types", "Priority support", "Best value"]'::jsonb),
                        ('lifetime', 'Lifetime Plan', 4999.00, NULL, '["Full access to all questions", "All challenge types", "VIP support", "All future content"]'::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        price_inr = EXCLUDED.price_inr,
                        duration_days = EXCLUDED.duration_days,
                        features = EXCLUDED.features;

                    INSERT INTO core.launch_config (id, is_active, trial_days, new_user_trial_days, coupon_grace_days)
                    VALUES (1, FALSE, 30, 7, 2)
                    ON CONFLICT (id) DO NOTHING;
                """)
                await conn_seed.close()
                print("Subscription plans and launch config seeded.")
            except Exception as e:
                print(f"Warning: Seed failed: {e}")
        except Exception as e:
            print(f"Warning: Migrations skipped or failed: {e}")


        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
