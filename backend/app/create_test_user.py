import asyncio
import uuid
import bcrypt
import asyncpg

DATABASE_URL = "postgres://postgres:postgres@postgres:5432/dailysql"

async def create_user():
    email = "test@example.com"
    password = "password123"
    full_name = "Test User"
    username = "testuser"
    
    # Hash password using bcrypt matching the backend context
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    print(f"Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    
    user_id = str(uuid.uuid4())
    
    print("Inserting user...")
    await conn.execute("""
        INSERT INTO core.users (user_id, email, hashed_password, auth_provider, full_name, username, onboarding_completed)
        VALUES ($1, $2, $3, 'email', $4, $5, true)
        ON CONFLICT (email) DO UPDATE SET 
            hashed_password = EXCLUDED.hashed_password,
            auth_provider = 'email',
            full_name = EXCLUDED.full_name,
            onboarding_completed = true
    """, user_id, email, hashed, full_name, username)
    
    print("Adding to whitelist...")
    await conn.execute("""
        INSERT INTO core.whitelist (email) VALUES ($1) ON CONFLICT DO NOTHING
    """, email)
    
    await conn.close()
    print("\nTest user created successfully!")
    print(f"Email: {email}")
    print(f"Password: {password}")

if __name__ == "__main__":
    asyncio.run(create_user())
