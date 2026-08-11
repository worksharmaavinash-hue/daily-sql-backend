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

            """)
            print("Migrations applied successfully.")
        except Exception as e:
            print(f"Warning: Migrations skipped or failed: {e}")
        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
