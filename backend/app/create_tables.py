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
        
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(init_db())
