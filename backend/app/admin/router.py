from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from uuid import uuid4
from app.db import get_pool
from app.admin.schemas import (
    ProblemCreate,
    DatasetCreate,
    SolutionCreate,
    DailyPracticeCreate
)
from app.execution.schema_manager import generate_schema_name, teardown_execution_schema
import json
import os
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID as PyUUID


def json_serial(obj):
    """Custom JSON serializer for types not serializable by default json."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, PyUUID):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

API_KEY_NAME = "X-Admin-Secret"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_admin_api_key(api_key: str = Security(api_key_header)):
    # Default to 'admin_secret' for local if env not set
    expected_secret = os.getenv("ADMIN_SECRET", "admin_secret")
    if api_key == expected_secret:
        return api_key
    raise HTTPException(status_code=403, detail="Could not validate credentials")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_api_key)])


# ============ GET ENDPOINTS (For Admin UI) ============

@router.get("/problems")
async def list_problems():
    """List all problems for admin selection dropdowns"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, difficulty, description, estimated_time_minutes, created_at
            FROM core.problems
            WHERE is_active = true
            ORDER BY created_at DESC
            """
        )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "difficulty": r["difficulty"],
            "description": r["description"][:100] + "..." if len(r["description"]) > 100 else r["description"],
            "estimated_time_minutes": r["estimated_time_minutes"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None
        }
        for r in rows
    ]


@router.get("/problems/{problem_id}")
async def get_problem_details(problem_id: str):
    """Get full problem details including datasets and solution"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        problem = await conn.fetchrow(
            "SELECT * FROM core.problems WHERE id = $1", problem_id
        )
        if not problem:
            raise HTTPException(status_code=404, detail="Problem not found")
        
        datasets = await conn.fetch(
            "SELECT id, table_name, schema_sql, seed_sql, sample_rows, column_types FROM core.problem_datasets WHERE problem_id = $1",
            problem_id
        )
        solution = await conn.fetchrow(
            "SELECT reference_query, order_sensitive, notes FROM core.problem_solutions WHERE problem_id = $1",
            problem_id
        )
    
    return {
        "id": str(problem["id"]),
        "title": problem["title"],
        "difficulty": problem["difficulty"],
        "description": problem["description"],
        "estimated_time_minutes": problem["estimated_time_minutes"],
        "datasets": [
            {
                "id": str(d["id"]),
                "table_name": d["table_name"],
                "schema_sql": d["schema_sql"],
                "seed_sql": d["seed_sql"],
                "sample_rows": d["sample_rows"],
                "column_types": d["column_types"]
            }
            for d in datasets
        ],
        "solution": {
            "reference_query": solution["reference_query"],
            "order_sensitive": solution["order_sensitive"],
            "notes": solution["notes"]
        } if solution else None
    }


@router.get("/schedule")
async def list_schedule():
    """List scheduled practices for the next 30 days and past 7 days"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT 
                dp.date,
                p1.id as easy_id, p1.title as easy_title,
                p2.id as medium_id, p2.title as medium_title,
                p3.id as advanced_id, p3.title as advanced_title
            FROM core.daily_practice dp
            LEFT JOIN core.problems p1 ON dp.easy_problem_id = p1.id
            LEFT JOIN core.problems p2 ON dp.medium_problem_id = p2.id
            LEFT JOIN core.problems p3 ON dp.advanced_problem_id = p3.id
            WHERE dp.date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY dp.date DESC
            """
        )
    return [
        {
            "date": r["date"].isoformat(),
            "easy": {"id": str(r["easy_id"]), "title": r["easy_title"]} if r["easy_id"] else None,
            "medium": {"id": str(r["medium_id"]), "title": r["medium_title"]} if r["medium_id"] else None,
            "advanced": {"id": str(r["advanced_id"]), "title": r["advanced_title"]} if r["advanced_id"] else None
        }
        for r in rows
    ]


# ============ POST ENDPOINTS (Create/Update/Delete) ============

@router.delete("/problems/{problem_id}")
async def delete_problem(problem_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # The schema doesn't have ON DELETE CASCADE, so we manually clean up references
            await conn.execute("DELETE FROM core.problem_datasets WHERE problem_id = $1", problem_id)
            await conn.execute("DELETE FROM core.problem_solutions WHERE problem_id = $1", problem_id)
            await conn.execute("DELETE FROM core.attempts WHERE problem_id = $1", problem_id)
            
            # Remove it from any daily practices
            await conn.execute("UPDATE core.daily_practice SET easy_problem_id = NULL WHERE easy_problem_id = $1", problem_id)
            await conn.execute("UPDATE core.daily_practice SET medium_problem_id = NULL WHERE medium_problem_id = $1", problem_id)
            await conn.execute("UPDATE core.daily_practice SET advanced_problem_id = NULL WHERE advanced_problem_id = $1", problem_id)
            
            # Finally, delete the problem
            result = await conn.execute(
                "DELETE FROM core.problems WHERE id = $1",
                problem_id
            )
            
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Problem not found")
    return {"message": "Problem deleted"}


@router.post("/problems")
async def create_problem(payload: ProblemCreate):
    pool = await get_pool()
    problem_id = uuid4()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.problems
            (id, title, difficulty, description, estimated_time_minutes)
            VALUES ($1, $2, $3, $4, $5)
            """,
            problem_id,
            payload.title,
            payload.difficulty,
            payload.description,
            payload.estimated_time_minutes,
        )

    return {"problem_id": str(problem_id)}

@router.post("/problems/{problem_id}/datasets")
async def add_dataset(problem_id: str, payload: DatasetCreate):
    pool = await get_pool()
    dataset_id = uuid4()

    async with pool.acquire() as conn:
        schema_name = generate_schema_name()
        
        try:
            await conn.execute(f'CREATE SCHEMA "{schema_name}"')
            await conn.execute(f'SET search_path TO "{schema_name}"')
            
            # Execute schemas and seed
            await conn.execute(payload.schema_sql)
            await conn.execute(payload.seed_sql)
            
            # Fetch sample rows
            records = await conn.fetch(f"SELECT * FROM {payload.table_name} LIMIT 10")
            sample_rows = [dict(record) for record in records]
        finally:
            await teardown_execution_schema(conn, schema_name)
            await conn.execute('SET search_path TO public')

        await conn.execute(
            """
            INSERT INTO core.problem_datasets
            (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            dataset_id,
            problem_id,
            payload.table_name,
            payload.schema_sql,
            payload.seed_sql,
            json.dumps(sample_rows, default=json_serial),
            json.dumps(payload.column_types),
        )

    return {"dataset_id": str(dataset_id)}

@router.post("/problems/{problem_id}/solution")
async def add_solution(problem_id: str, payload: SolutionCreate):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.problem_solutions
            (problem_id, reference_query, order_sensitive, notes)
            VALUES ($1, $2, $3, $4)
            """,
            problem_id,
            payload.reference_query,
            payload.order_sensitive,
            payload.notes,
        )

    return {"status": "solution_saved"}

@router.post("/daily-practice")
async def schedule_daily_practice(payload: DailyPracticeCreate):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.daily_practice
            (date, easy_problem_id, medium_problem_id, advanced_problem_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (date)
            DO UPDATE SET
                easy_problem_id = EXCLUDED.easy_problem_id,
                medium_problem_id = EXCLUDED.medium_problem_id,
                advanced_problem_id = EXCLUDED.advanced_problem_id
            """,
            payload.date,
            payload.easy_problem_id,
            payload.medium_problem_id,
            payload.advanced_problem_id,
        )

    return {"status": "scheduled"}
