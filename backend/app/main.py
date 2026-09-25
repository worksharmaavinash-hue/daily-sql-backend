from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.execution.router import router as execution_router
from app.admin.router import router as admin_router
from app.user.router import router as user_router
from app.auth.router import router as auth_router
from app.votes.router import router as votes_router
from app.comments.router import router as comments_router
from app.feedback.router import router as feedback_router
from app.payments.router import router as payments_router
from app.coupons.router import router as coupons_router
from app.announcements.router import router as announcements_router
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks, then yield for request handling."""
    try:
        from app.db import get_pool
        from app.payments.subscription_service import expire_stale_subscriptions
        pool = await get_pool()
        async with pool.acquire() as conn:
            await expire_stale_subscriptions(conn)
        print("[Startup] Stale subscriptions swept.")
    except Exception as e:
        print(f"[Startup] Could not sweep subscriptions: {e}")
    yield   # App runs here


app = FastAPI(lifespan=lifespan)

# CORS origins: configurable via CORS_ORIGINS env var (comma-separated)
# Defaults to localhost + production domains
_default_origins = "http://localhost:3000,http://127.0.0.1:3000,https://www.dailysql.in,https://dailysql.in"
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
app.include_router(admin_router)
app.include_router(execution_router)
app.include_router(user_router)
app.include_router(votes_router)
app.include_router(comments_router)
app.include_router(feedback_router)
app.include_router(payments_router)
app.include_router(coupons_router)
app.include_router(announcements_router)



@app.get("/health")
def health():
    return {"status": "ok"}
