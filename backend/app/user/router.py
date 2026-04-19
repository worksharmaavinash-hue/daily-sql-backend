import json
import os
from fastapi import APIRouter, HTTPException, Depends
from datetime import date
from app.db import get_pool
from app.auth.jwt import verify_jwt
from pydantic import BaseModel
from typing import Optional, List
import time
from app.user.cloudinary_utils import generate_cloudinary_signature
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

# Validate Cloudinary credentials on startup
if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    print("Warning: Cloudinary credentials not fully configured in environment variables.")


router = APIRouter(prefix="", tags=["user"])

@router.get("/practice/today")
async def get_today_practice():
    pool = await get_pool()
    today = (datetime.now(IST) - timedelta(hours=1)).date()

    async with pool.acquire() as conn:
        # Cleanup & Publish Logic: 
        # 1. Permanently publish (undraft) problems as soon as their scheduled date is reached
        await conn.execute(
            """
            UPDATE core.problems
            SET is_active = true
            WHERE id IN (
                SELECT easy_problem_id FROM core.daily_practice WHERE date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
                UNION
                SELECT medium_problem_id FROM core.daily_practice WHERE date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
                UNION
                SELECT advanced_problem_id FROM core.daily_practice WHERE date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
            ) AND is_active = false
            """
        )
        
        # 2. Remove schedule history records older than 7 days (as requested)
        await conn.execute(
            "DELETE FROM core.daily_practice WHERE date < ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date - INTERVAL '7 days'"
        )

        # Try today first
        row = await conn.fetchrow(
            """
            SELECT date, easy_problem_id, medium_problem_id, advanced_problem_id
            FROM core.daily_practice
            WHERE date = $1
            """,
            today,
        )

        # Fallback to latest past/current
        if not row:
            row = await conn.fetchrow(
                """
                SELECT date, easy_problem_id, medium_problem_id, advanced_problem_id
                FROM core.daily_practice
                WHERE date <= $1
                ORDER BY date DESC
                LIMIT 1
                """,
                today,
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
            WHERE id = $1 AND (is_active = true OR EXISTS (
                SELECT 1 FROM core.daily_practice 
                WHERE (easy_problem_id = core.problems.id OR medium_problem_id = core.problems.id OR advanced_problem_id = core.problems.id)
                AND date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
            ))
            """,
            problem_id,
        )

    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    return dict(problem)

@router.get("/problems")
async def list_problems():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, difficulty, description, estimated_time_minutes
            FROM core.problems
            WHERE is_active = true OR EXISTS (
                SELECT 1 FROM core.daily_practice 
                WHERE (easy_problem_id = core.problems.id OR medium_problem_id = core.problems.id OR advanced_problem_id = core.problems.id)
                AND date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
            )
            ORDER BY created_at DESC
            """
        )
    return [dict(r) for r in rows]

@router.get("/problems/{problem_id}/datasets")
async def get_problem_datasets(problem_id: str):
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, table_name, schema_sql, seed_sql, sample_rows, column_types
            FROM core.problem_datasets
            WHERE problem_id = $1
            """,
            problem_id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="No datasets found")

    return [
        {
            "id": str(r["id"]),
            "table_name": r["table_name"],
            "schema_sql": r["schema_sql"],
            "seed_sql": r["seed_sql"],
            "sample_rows": json.loads(r["sample_rows"]) if isinstance(r["sample_rows"], str) else r["sample_rows"],
            "column_types": json.loads(r["column_types"]) if isinstance(r["column_types"], str) else r["column_types"],
        }
        for r in rows
    ]

@router.get("/problems/{problem_id}/expected")
async def get_expected_output(problem_id: str):
    """Run the reference query and return the expected output columns + rows."""
    from app.execution.schema_manager import setup_execution_schema, teardown_execution_schema
    from app.execution.runner import execute_user_query, QueryExecutionError

    pool = await get_pool()

    async with pool.acquire() as conn:
        # Get the reference query
        sol_row = await conn.fetchrow(
            "SELECT reference_query FROM core.problem_solutions WHERE problem_id = $1",
            problem_id,
        )
        if not sol_row:
            raise HTTPException(status_code=404, detail="No solution found for this problem")

        schema_name = None
        try:
            schema_name = await setup_execution_schema(conn, problem_id)
            result = await execute_user_query(conn, sol_row["reference_query"])
            return {
                "columns": result["columns"],
                "rows": result["rows"],
            }
        except QueryExecutionError as e:
            raise HTTPException(status_code=500, detail=f"Failed to compute expected output: {e}")
        finally:
            if schema_name:
                await teardown_execution_schema(conn, schema_name)

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
    today = (datetime.now(IST) - timedelta(hours=1)).date()

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

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    occupation: Optional[str] = None
    job_role: Optional[str] = None
    experience_years: Optional[int] = None
    avatar_url: Optional[str] = None

@router.get("/me/profile")
async def get_my_profile(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            """
            SELECT user_id, email, full_name, occupation, job_role, experience_years, avatar_url, onboarding_completed, created_at
            FROM core.users
            WHERE user_id = $1
            """,
            user_id
        )

        if not profile:
            return {"exists": False, "in_waitlist": False, "email": user.get("email")}

    return {
        "exists": True,
        **dict(profile)
    }

@router.post("/me/profile")
async def update_my_profile(data: ProfileUpdate, user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]
    email = user.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="Email required from token")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.users (user_id, email, full_name, occupation, job_role, experience_years, avatar_url, onboarding_completed)
            VALUES ($1, $2, $3, $4, $5, $6, $7, true)
            ON CONFLICT (user_id) DO UPDATE SET
                full_name = COALESCE(EXCLUDED.full_name, core.users.full_name),
                occupation = COALESCE(EXCLUDED.occupation, core.users.occupation),
                job_role = COALESCE(EXCLUDED.job_role, core.users.job_role),
                experience_years = COALESCE(EXCLUDED.experience_years, core.users.experience_years),
                avatar_url = COALESCE(EXCLUDED.avatar_url, core.users.avatar_url),
                onboarding_completed = true
            """,
            user_id,
            email,
            data.full_name,
            data.occupation,
            data.job_role,
            data.experience_years,
            data.avatar_url
        )

    return {"status": "success"}

@router.get("/me/solutions/{problem_id}")
async def get_my_solution(problem_id: str, user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT submitted_query FROM core.user_solutions WHERE user_id = $1 AND problem_id = $2",
            user_id,
            problem_id
        )

    if not row:
        return {"submitted_query": None}

    return {"submitted_query": row["submitted_query"]}

@router.get("/me/stats")
async def get_my_stats(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        # Get count of distinct problems solved by difficulty
        rows = await conn.fetch(
            """
            SELECT p.difficulty, COUNT(DISTINCT us.problem_id) as solved
            FROM core.user_solutions us
            JOIN core.problems p ON us.problem_id = p.id
            WHERE us.user_id = $1
            GROUP BY p.difficulty
            """,
            user_id
        )
        
        # Get total problem counts by difficulty
        totals = await conn.fetch(
            """
            SELECT difficulty, COUNT(*) as total
            FROM core.problems
            WHERE is_active = true OR EXISTS (
                SELECT 1 FROM core.daily_practice 
                WHERE (easy_problem_id = core.problems.id OR medium_problem_id = core.problems.id OR advanced_problem_id = core.problems.id)
                AND date <= ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata') - INTERVAL '1 hour')::date
            )
            GROUP BY difficulty
            """
        )

    stats = {
        "easy": {"solved": 0, "total": 0},
        "medium": {"solved": 0, "total": 0},
        "advanced": {"solved": 0, "total": 0}
    }

    for r in totals:
        diff = r["difficulty"].lower()
        if diff in stats:
            stats[diff]["total"] = r["total"]
            
    for r in rows:
        diff = r["difficulty"].lower()
        if diff in stats:
            stats[diff]["solved"] = r["solved"]

    return stats

@router.get("/me/submissions")
async def get_recent_submissions(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT us.problem_id, p.title, p.difficulty, us.created_at
            FROM core.user_solutions us
            JOIN core.problems p ON us.problem_id = p.id
            WHERE us.user_id = $1
            ORDER BY us.created_at DESC
            LIMIT 10
            """,
            user_id
        )

    return [
        {
            "id": r["problem_id"],
            "title": r["title"],
            "difficulty": r["difficulty"].lower(),
            "created_at": r["created_at"]
        }
        for r in rows
    ]

@router.get("/me/heatmap")
async def get_practice_heatmap(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT attempt_date, COUNT(*) as count
            FROM core.attempts
            WHERE user_id = $1 AND status = 'correct'
            GROUP BY attempt_date
            ORDER BY attempt_date DESC
            LIMIT 365
            """,
            user_id
        )

    return {str(r["attempt_date"]): r["count"] for r in rows}

@router.get("/leaderboard")
async def get_leaderboard():
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.user_id,
                u.full_name,
                u.avatar_url,
                u.job_role,
                u.occupation,
                COUNT(DISTINCT us.problem_id) AS total_solved,
                COALESCE(s.current_streak, 0) AS current_streak
            FROM core.user_solutions us
            JOIN core.users u ON us.user_id = u.user_id
            LEFT JOIN core.streaks s ON u.user_id = s.user_id
            GROUP BY u.user_id, u.full_name, u.avatar_url, u.job_role, u.occupation, s.current_streak
            ORDER BY total_solved DESC, current_streak DESC
            LIMIT 20
            """
        )

    return [
        {
            "user_id": str(r["user_id"]),
            "full_name": r["full_name"] or "Anonymous",
            "avatar_url": r["avatar_url"],
            "job_role": r["job_role"] or r["occupation"] or "Member",
            "total_solved": r["total_solved"],
            "current_streak": r["current_streak"],
        }
        for r in rows
    ]


@router.get("/me/solved-ids")
async def get_my_solved_ids(user=Depends(verify_jwt)):
    pool = await get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT problem_id FROM core.user_solutions WHERE user_id = $1",
            user_id,
        )

    return {"solved_ids": [str(r["problem_id"]) for r in rows]}


@router.get("/me/cloudinary-signature")
async def get_cloudinary_signature(user=Depends(verify_jwt)):
    user_id = user["user_id"]
    timestamp = int(time.time())
    
    # We use user_id in public_id for uniqueness/identification
    public_id = f"user_{user_id.replace('-', '_')}"
    folder = "profile_photos"
    
    params = {
        "timestamp": timestamp,
        "public_id": public_id,
        "folder": folder
    }
    
    signature = generate_cloudinary_signature(params, CLOUDINARY_API_SECRET)
    
    return {
        "signature": signature,
        "timestamp": timestamp,
        "api_key": CLOUDINARY_API_KEY,
        "cloud_name": CLOUDINARY_CLOUD_NAME,
        "public_id": public_id,
        "folder": folder
    }

