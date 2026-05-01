import asyncio
import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/dailysql")

async def migrate():
    print(f"Connecting to {DATABASE_URL}...")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Check if constraint exists before dropping
        # The constraint name for UNIQUE (user_id, problem_id, attempt_date) is likely:
        # core.attempts_user_id_problem_id_attempt_date_key
        
        print("Dropping unique constraint if exists...")
        await conn.execute("""
            ALTER TABLE core.attempts 
            DROP CONSTRAINT IF EXISTS attempts_user_id_problem_id_attempt_date_key;
        """)
        print("Migration successful.")
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
