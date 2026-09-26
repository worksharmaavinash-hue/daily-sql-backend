1import asyncio
import os
import sys
import uuid
import asyncpg
import bcrypt

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/dailysql")

def _hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")

async def seed_staff(email: str, password: str, full_name: str, role: str = "admin"):
    print(f"Connecting to database at {DATABASE_URL}...")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Ensure staff table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS core.staff_users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('writer', 'admin', 'superadmin')),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_login_at TIMESTAMP WITH TIME ZONE,
                created_by UUID REFERENCES core.staff_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS staff_users_email_idx ON core.staff_users (LOWER(email));
            CREATE INDEX IF NOT EXISTS staff_users_role_idx ON core.staff_users (role);
        """)

        hashed = _hash_password(password)
        clean_email = email.strip().lower()

        existing = await conn.fetchrow(
            "SELECT id, role FROM core.staff_users WHERE LOWER(email) = $1", clean_email
        )

        if existing:
            await conn.execute(
                """
                UPDATE core.staff_users
                SET hashed_password = $1, full_name = $2, role = $3, is_active = true, updated_at = NOW()
                WHERE id = $4
                """,
                hashed,
                full_name,
                role,
                existing["id"],
            )
            print(f"✅ Updated existing staff user: {clean_email} (Role: {role})")
        else:
            new_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO core.staff_users (id, email, hashed_password, full_name, role, is_active)
                VALUES ($1, $2, $3, $4, $5, true)
                """,
                new_id,
                clean_email,
                hashed,
                full_name,
                role,
            )
            print(f"✅ Created new staff user: {clean_email} (Role: {role}, ID: {new_id})")

    finally:
        await conn.close()

if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@dailysql.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "Admin@123456"
    full_name = sys.argv[3] if len(sys.argv) > 3 else "Platform Admin"
    role = sys.argv[4] if len(sys.argv) > 4 else "admin"

    asyncio.run(seed_staff(email, password, full_name, role))
