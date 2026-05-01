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
                ALTER TABLE core.problem_datasets ADD COLUMN IF NOT EXISTS column_types JSONB NOT NULL DEFAULT '{}'::jsonb;
                CREATE TABLE IF NOT EXISTS core.whitelist (
                    email TEXT PRIMARY KEY,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS core.waitlist (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    whatsapp_number TEXT,
                    occupation TEXT,
                    job_role TEXT,
                    experience_years INTEGER,
                    source TEXT,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            print("Migrations applied successfully.")
        except Exception as e:
            print(f"Warning: Migrations skipped or failed: {e}")
        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
