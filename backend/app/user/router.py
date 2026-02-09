from fastapi import APIRouter, HTTPException
from datetime import date
from datetime import date
from app.db import get_pool
from app.auth.jwt import verify_jwt
from fastapi import Depends

router = APIRouter(prefix="", tags=["user"])

@router.get("/practice/today")
async def get_today_practice():
    pool = await get_pool()
    today = date.today()

    async with pool.acquire() as conn:
        # Try today first
        row = await conn.fetchrow(
            """
            SELECT date, easy_problem_id, medium_problem_id, advanced_problem_id
            FROM core.daily_practice
            WHERE date = $1
            """,
            today,
        )

        # Fallback to latest
        if not row:
            row = await conn.fetchrow(
                """
                SELECT date, easy_problem_id, medium_problem_id, advanced_problem_id
                FROM core.daily_practice
                ORDER BY date DESC
                LIMIT 1
                """
            )

    if not row:
        raise HTTPException(status_code=404, detail="No practice set found")

    return {
        "date": row["date"],
        "easy": row["easy_problem_id"],
        "medium": row["medium_problem_id"],
        "advanced": row["advanced_problem_id"],
    }

@router.get("/problems/{problem_id}")
async def get_problem(problem_id: str):
    pool = await get_pool()

    async with pool.acquire() as conn:
        problem = await conn.fetchrow(
            """
            SELECT id, title, difficulty, description, estimated_time_minutes
            FROM core.problems
            WHERE id = $1 AND is_active = true
            """,
            problem_id,
        )

    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    return dict(problem)

@router.get("/problems/{problem_id}/datasets")
async def get_problem_datasets(problem_id: str):
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name, schema_sql, sample_rows
            FROM core.problem_datasets
            WHERE problem_id = $1
            """,
            problem_id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="No datasets found")

    return [
        {
            "table_name": r["table_name"],
            "schema_sql": r["schema_sql"],
            "sample_rows": r["sample_rows"],
        }
        for r in rows
    ]

@router.get("/me/streak")
async def get_my_streak(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_streak, last_active_date
            FROM core.streaks
            WHERE user_id = $1
            """,
            user_id,
        )

    if not row:
        return {"current_streak": 0, "last_active_date": None}

    return {
        "current_streak": row["current_streak"],
        "last_active_date": row["last_active_date"],
    }

@router.get("/me/attempts/today")
async def get_today_attempts(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]
    today = date.today()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT problem_id, status, execution_time_ms
            FROM core.attempts
            WHERE user_id = $1 AND attempt_date = $2
            """,
            user_id,
            today,
        )

    return [
        {
            "problem_id": str(r["problem_id"]),
            "status": r["status"],
            "execution_time_ms": r["execution_time_ms"],
        }
        for r in rows
    ]
