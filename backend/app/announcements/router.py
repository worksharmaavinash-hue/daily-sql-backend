"""
Announcements router — Dynamic Announcement Banner management.

Endpoints:
  GET  /api/announcements/active  → Public endpoint to get currently active announcement
  GET  /api/admin/announcement    → Admin endpoint to get announcement settings
  PUT  /api/admin/announcement    → Admin endpoint to update announcement settings
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from pydantic import BaseModel
from typing import Optional
from app.db import get_pool
from app.admin.router import get_admin_api_key

router = APIRouter(tags=["announcements"])


class AnnouncementUpdate(BaseModel):
    is_active: bool = True
    badge_text: str = "NEW"
    message_text: str = "9 fresh problems every day — SQL, Python & PySpark."
    link_text: str = "Sign up free"
    link_url: str = "/signup"


async def ensure_announcements_table(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS core.announcements (
            id SERIAL PRIMARY KEY,
            is_active BOOLEAN DEFAULT TRUE,
            badge_text VARCHAR(50) DEFAULT 'NEW',
            message_text TEXT NOT NULL DEFAULT '9 fresh problems every day — SQL, Python & PySpark.',
            link_text VARCHAR(100) DEFAULT 'Sign up free',
            link_url VARCHAR(255) DEFAULT '/signup',
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        INSERT INTO core.announcements (id, is_active, badge_text, message_text, link_text, link_url)
        VALUES (1, TRUE, 'NEW', '9 fresh problems every day — SQL, Python & PySpark.', 'Sign up free', '/signup')
        ON CONFLICT (id) DO NOTHING;
    """)


# ── 1. Public endpoint (Landing Page & Visitors) ──────────────────────────────
@router.get("/api/announcements/active")
async def get_active_announcement():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await ensure_announcements_table(conn)
        row = await conn.fetchrow(
            "SELECT is_active, badge_text, message_text, link_text, link_url, updated_at FROM core.announcements WHERE id = 1"
        )
        if not row:
            return {
                "is_active": True,
                "badge_text": "NEW",
                "message_text": "9 fresh problems every day — SQL, Python & PySpark.",
                "link_text": "Sign up free",
                "link_url": "/signup",
            }

        return {
            "is_active": bool(row["is_active"]),
            "badge_text": row["badge_text"] or "NEW",
            "message_text": row["message_text"] or "",
            "link_text": row["link_text"] or "",
            "link_url": row["link_url"] or "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


# ── 2. Admin GET endpoint ───────────────────────────────────────────────────
@router.get("/admin/announcement", dependencies=[Depends(get_admin_api_key)])
@router.get("/api/admin/announcement", dependencies=[Depends(get_admin_api_key)])
async def get_admin_announcement():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await ensure_announcements_table(conn)
        row = await conn.fetchrow(
            "SELECT is_active, badge_text, message_text, link_text, link_url, updated_at FROM core.announcements WHERE id = 1"
        )
        if not row:
            return {
                "is_active": True,
                "badge_text": "NEW",
                "message_text": "9 fresh problems every day — SQL, Python & PySpark.",
                "link_text": "Sign up free",
                "link_url": "/signup",
            }

        return {
            "is_active": bool(row["is_active"]),
            "badge_text": row["badge_text"] or "NEW",
            "message_text": row["message_text"] or "",
            "link_text": row["link_text"] or "",
            "link_url": row["link_url"] or "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


# ── 3. Admin PUT endpoint ───────────────────────────────────────────────────
@router.put("/admin/announcement", dependencies=[Depends(get_admin_api_key)])
@router.post("/admin/announcement", dependencies=[Depends(get_admin_api_key)])
@router.put("/api/admin/announcement", dependencies=[Depends(get_admin_api_key)])
@router.post("/api/admin/announcement", dependencies=[Depends(get_admin_api_key)])
async def update_admin_announcement(payload: AnnouncementUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await ensure_announcements_table(conn)
        await conn.execute(
            """
            INSERT INTO core.announcements (id, is_active, badge_text, message_text, link_text, link_url, updated_at)
            VALUES (1, $1, $2, $3, $4, $5, NOW())
            ON CONFLICT (id) DO UPDATE SET
                is_active = EXCLUDED.is_active,
                badge_text = EXCLUDED.badge_text,
                message_text = EXCLUDED.message_text,
                link_text = EXCLUDED.link_text,
                link_url = EXCLUDED.link_url,
                updated_at = NOW();
            """,
            payload.is_active,
            payload.badge_text,
            payload.message_text,
            payload.link_text,
            payload.link_url,
        )

    return {"success": True, "message": "Announcement banner updated successfully"}
