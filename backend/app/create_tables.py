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
            """)
            print("Migrations applied successfully.")
        except Exception as e:
            print(f"Warning: Migrations skipped or failed: {e}")
        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
