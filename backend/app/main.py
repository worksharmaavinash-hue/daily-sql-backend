from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.execution.router import router as execution_router
from app.admin.router import router as admin_router
from app.user.router import router as user_router
from app.auth.router import router as auth_router
from app.auth.cms_auth_router import router as cms_auth_router
from app.votes.router import router as votes_router
from app.comments.router import router as comments_router
from app.feedback.router import router as feedback_router
from app.payments.router import router as payments_router
from app.coupons.router import router as coupons_router
import app.metrics
from app.announcements.router import router as announcements_router
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks, then yield for request handling."""
    try:
        import bcrypt
        from app.db import get_pool
        from app.payments.subscription_service import expire_stale_subscriptions
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 1. Ensure core schema and staff_users table exist
            await conn.execute("""
                CREATE SCHEMA IF NOT EXISTS core;
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
                CREATE INDEX IF NOT EXISTS staff_users_active_idx ON core.staff_users (is_active);
            """)

            await conn.execute("ALTER TABLE core.users ADD COLUMN IF NOT EXISTS phone_number TEXT")

            # 2. Auto-seed default superadmin if no staff exist
            count = await conn.fetchval("SELECT COUNT(*) FROM core.staff_users")
            if count == 0:
                default_pass = "Admin@123456"
                salt = bcrypt.gensalt()
                hashed = bcrypt.hashpw(default_pass.encode("utf-8"), salt).decode("utf-8")
                await conn.execute(
                    """
                    INSERT INTO core.staff_users (email, hashed_password, full_name, role, is_active)
                    VALUES ($1, $2, $3, $4, true)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    "admin@dailysql.com",
                    hashed,
                    "Platform Superadmin",
                    "admin",
                )
                print("[Startup] Initialized default staff admin: admin@dailysql.com (Password: Admin@123456)")

            # 3. Sweep stale subscriptions
            await expire_stale_subscriptions(conn)
            print("[Startup] Stale subscriptions swept.")
    except Exception as e:
        print(f"[Startup] Startup initialization notice: {e}")

    # Pricing columns/audit table (idempotent; safe to run on every start)
    try:
        from app.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                ALTER TABLE core.subscription_plans ADD COLUMN IF NOT EXISTS original_price_inr NUMERIC(10,2);
                ALTER TABLE core.subscription_plans ADD COLUMN IF NOT EXISTS sort_order INTEGER;
                ALTER TABLE core.subscriptions ADD COLUMN IF NOT EXISTS expected_amount NUMERIC(10,2);
                CREATE TABLE IF NOT EXISTS core.plan_price_audit (
                    id BIGSERIAL PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    old_price NUMERIC(10,2),
                    new_price NUMERIC(10,2),
                    old_original_price NUMERIC(10,2),
                    new_original_price NUMERIC(10,2),
                    old_is_active BOOLEAN,
                    new_is_active BOOLEAN,
                    changed_by TEXT,
                    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                UPDATE core.subscription_plans SET sort_order = CASE id WHEN 'monthly' THEN 1 WHEN 'yearly' THEN 2 WHEN 'lifetime' THEN 3 END
                    WHERE sort_order IS NULL;
                UPDATE core.subscription_plans SET original_price_inr = CASE id WHEN 'monthly' THEN 1299 WHEN 'yearly' THEN 3499 WHEN 'lifetime' THEN 9999 END
                    WHERE original_price_inr IS NULL;
            """)
    except Exception as e:
        print(f"[Startup] Pricing migration notice: {e}")
    yield   # App runs here



app = FastAPI(lifespan=lifespan)

# CORS origins: configurable via CORS_ORIGINS env var (comma-separated)
# Defaults to localhost (3000, 3001 for CMS) + production domains
_default_origins = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3001,http://127.0.0.1:3001,"
    "https://www.dailysql.in,https://dailysql.in,"
    "https://cms.dailysql.in,https://cms.dailysql.com"
)
origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(cms_auth_router)
app.include_router(admin_router)
app.include_router(execution_router)

app.include_router(user_router)
app.include_router(votes_router)
app.include_router(comments_router)
app.include_router(feedback_router)
app.include_router(payments_router)
app.include_router(coupons_router)
app.include_router(announcements_router)

# Razorpay test harness (admin-only, 404 to everyone else, never grants plans) — opt-in via env flag
if os.getenv("RAZORPAY_TEST_HARNESS", "").lower() in ("1", "true", "yes"):
    from app.payments.razorpay_test_router import router as razorpay_test_router
    app.include_router(razorpay_test_router)
    print("[Startup] Razorpay test harness mounted at /api/rzp-test")

# Prometheus Metrics Exporter
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics", "/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
    print("[Startup] Prometheus metrics instrumented at /metrics")
except Exception as e:
    print(f"[Startup] Prometheus instrumentation notice: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}

