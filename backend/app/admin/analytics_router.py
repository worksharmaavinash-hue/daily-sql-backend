from fastapi import APIRouter, Depends, HTTPException
from app.db import get_pool
from app.auth.jwt import verify_jwt
from datetime import date, timedelta
from typing import List, Dict, Any

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/summary")
async def get_analytics_summary():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # DAU / WAU / MAU
        dau = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM core.attempts WHERE attempt_date = CURRENT_DATE")
        wau = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM core.attempts WHERE attempt_date > CURRENT_DATE - INTERVAL '7 days'")
        mau = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM core.attempts WHERE attempt_date > CURRENT_DATE - INTERVAL '30 days'")
        
        # New Signups (Last 7 days)
        signups_7d = await conn.fetch("SELECT created_at::date as date, COUNT(*) as count FROM core.users WHERE created_at > CURRENT_DATE - INTERVAL '7 days' GROUP BY 1 ORDER BY 1")
        
        # Total Users
        total_users = await conn.fetchval("SELECT COUNT(*) FROM core.users")
        total_waitlist = await conn.fetchval("SELECT COUNT(*) FROM core.waitlist")

        return {
            "dau": dau or 0,
            "wau": wau or 0,
            "mau": mau or 0,
            "total_users": total_users or 0,
            "total_waitlist": total_waitlist or 0,
            "signups_trend": [{"date": r["date"], "count": r["count"]} for r in signups_7d]
        }

@router.get("/problems")
async def get_problem_performance():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Success Rate & Popularity
        stats = await conn.fetch("""
            SELECT 
                p.id, 
                p.title,
                p.difficulty,
                COUNT(a.id) as total_attempts,
                COUNT(DISTINCT a.user_id) as unique_users,
                COUNT(a.id) FILTER (WHERE a.status = 'correct') as successful_attempts,
                (COUNT(a.id) FILTER (WHERE a.status = 'correct')::float / NULLIF(COUNT(a.id), 0)) * 100 as success_rate
            FROM core.problems p
            LEFT JOIN core.attempts a ON p.id = a.problem_id
            GROUP BY p.id, p.title, p.difficulty
            ORDER BY total_attempts DESC
        """)

        return [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "difficulty": r["difficulty"],
                "total_attempts": r["total_attempts"],
                "unique_users": r["unique_users"],
                "success_rate": round(r["success_rate"] or 0, 1)
            }
            for r in stats
        ]

@router.get("/retention")
async def get_retention_data():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Streak Distribution
        streaks = await conn.fetch("""
            SELECT 
                CASE 
                    WHEN current_streak = 0 THEN '0'
                    WHEN current_streak BETWEEN 1 AND 5 THEN '1-5'
                    WHEN current_streak BETWEEN 6 AND 10 THEN '6-10'
                    WHEN current_streak BETWEEN 11 AND 15 THEN '11-15'
                    WHEN current_streak BETWEEN 16 AND 20 THEN '16-20'
                    ELSE '21+'
                END as streak_range,
                COUNT(*) as count
            FROM core.streaks
            GROUP BY 1
            ORDER BY MIN(current_streak)
        """)

        # Basic Cohort Analysis (Simplified: Users who solved in Week X vs Signup Week)
        # To keep it simple, we'll just return the counts for now
        cohorts = await conn.fetch("""
            WITH user_signup_week AS (
                SELECT user_id, date_trunc('week', created_at) as signup_week
                FROM core.users
            ),
            user_activity_weeks AS (
                SELECT DISTINCT user_id, date_trunc('week', created_at) as activity_week
                FROM core.attempts
            )
            SELECT 
                signup_week,
                activity_week,
                COUNT(DISTINCT a.user_id) as active_users
            FROM user_signup_week s
            JOIN user_activity_weeks a ON s.user_id = a.user_id
            WHERE activity_week >= signup_week
            GROUP BY 1, 2
            ORDER BY 1, 2
        """)

        return {
            "streaks": [{"range": r["streak_range"], "count": r["count"]} for r in streaks],
            "cohorts": [{"signup_week": r["signup_week"], "activity_week": r["activity_week"], "users": r["active_users"]} for r in cohorts]
        }

@router.get("/demographics")
async def get_demographics():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Normalized and grouped demographics
        roles = await conn.fetch("""
            SELECT 
                CASE 
                    WHEN job_role ILIKE '%backend%' THEN 'Backend Engineering'
                    WHEN job_role ILIKE '%frontend%' THEN 'Frontend Engineering'
                    WHEN job_role ILIKE '%fullstack%' OR job_role ILIKE '%full%stack%' THEN 'Fullstack Engineering'
                    WHEN job_role ILIKE '%data%scientist%' OR job_role ILIKE '%data%science%' THEN 'Data Science'
                    WHEN job_role ILIKE '%data%engineer%' THEN 'Data Engineering'
                    WHEN job_role ILIKE '%analyst%' OR job_role ILIKE '%analytics%' THEN 'Data Analytics'
                    WHEN job_role ILIKE '%product%' THEN 'Product Management'
                    WHEN job_role ILIKE '%student%' THEN 'Education/Student'
                    WHEN job_role ILIKE '%manager%' OR job_role ILIKE '%lead%' THEN 'Management/Leadership'
                    ELSE INITCAP(job_role)
                END as normalized_role,
                COUNT(*) as count
            FROM (
                SELECT job_role FROM core.waitlist WHERE job_role IS NOT NULL
                UNION ALL
                SELECT job_role FROM core.users WHERE job_role IS NOT NULL
            ) combined
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        """)
        
        experience = await conn.fetch("""
            SELECT 
                CASE 
                    WHEN experience_years < 2 THEN 'Junior (0-2y)'
                    WHEN experience_years BETWEEN 2 AND 5 THEN 'Mid-Level (2-5y)'
                    WHEN experience_years BETWEEN 6 AND 10 THEN 'Senior (6-10y)'
                    WHEN experience_years BETWEEN 11 AND 15 THEN 'Staff/Lead (11-15y)'
                    ELSE 'Veteran (15y+)'
                END as range,
                COUNT(*) as count,
                MIN(experience_years) as sort_order
            FROM (
                SELECT experience_years FROM core.waitlist WHERE experience_years IS NOT NULL
                UNION ALL
                SELECT experience_years FROM core.users WHERE experience_years IS NOT NULL
            ) combined
            GROUP BY 1 ORDER BY sort_order
        """)

        return {
            "roles": [{"name": r["normalized_role"], "value": r["count"]} for r in roles],
            "experience": [{"years": r["range"], "count": r["count"]} for r in experience]
        }

@router.get("/sentiment")
async def get_sentiment():
    pool = await get_pool()
    async with pool.acquire() as conn:
        sentiment = await conn.fetch("""
            SELECT * FROM (
                SELECT 
                    p.id, 
                    p.title,
                    (SELECT COUNT(*) FROM core.problem_votes v WHERE v.problem_id = p.id) as likes,
                    (SELECT COUNT(*) FROM core.comments c WHERE c.problem_id = p.id) as comments
                FROM core.problems p
            ) sub
            ORDER BY (likes + comments) DESC
            LIMIT 20
        """)

        return [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "likes": r["likes"],
                "comments": r["comments"]
            }
            for r in sentiment
        ]
