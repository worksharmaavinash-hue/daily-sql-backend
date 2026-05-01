import asyncio
import os
import secrets
import string
import asyncpg

DB_URL = os.getenv("DATABASE_URL")

async def main():
    if not DB_URL:
        print("DATABASE_URL not found")
        return
        
    conn = await asyncpg.connect(DB_URL)
    
    # 1. Add columns if they don't exist
    print("Adding columns...")
    await conn.execute("""
        ALTER TABLE core.users
        ADD COLUMN IF NOT EXISTS username TEXT UNIQUE,
        ADD COLUMN IF NOT EXISTS is_public_profile BOOLEAN DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS bio TEXT,
        ADD COLUMN IF NOT EXISTS linkedin_url TEXT,
        ADD COLUMN IF NOT EXISTS github_url TEXT,
        ADD COLUMN IF NOT EXISTS profile_updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
    """)

    # 2. Assign usernames to existing users
    print("Fetching users without a username...")
    users = await conn.fetch("SELECT user_id, email FROM core.users WHERE username IS NULL")
    print(f"Found {len(users)} users needing a username.")

    for user in users:
        base_username = user['email'].split('@')[0]
        # Remove special characters, keep alphanumeric and hyphens
        base_username = "".join(c for c in base_username if c.isalnum() or c == '-').lower()
        if not base_username:
            base_username = "user"
            
        username = base_username
        
        while True:
            try:
                await conn.execute("UPDATE core.users SET username = $1 WHERE user_id = $2", username, user['user_id'])
                print(f"Assigned {username} to {user['email']}")
                break
            except asyncpg.exceptions.UniqueViolationError:
                suffix = ''.join(secrets.choice(string.hexdigits) for i in range(4)).lower()
                username = f"{base_username}-{suffix}"

    await conn.close()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
