from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from app.execution.validator import validate_sql
from app.db import get_pool
from app.execution.schema_manager import (
    setup_execution_schema,
    teardown_execution_schema,
    apply_execution_limits
)
from app.execution.problem_guard import ensure_problem_exists
from app.execution.runner import execute_user_query, QueryExecutionError
from app.execution.judge import compare_results
from app.attempts.service import record_attempt
from app.streaks.service import update_streak
from app.auth.jwt import verify_jwt, verify_jwt_optional
from app.rate_limit.limiter import rate_limit
from typing import Optional

router = APIRouter(prefix="/execute", tags=["execution"])

class ExecuteRequest(BaseModel):
    problem_id: str
    query: str


@router.post("")
async def execute_query(
    payload: ExecuteRequest,
    user: Optional[dict] = Depends(verify_jwt_optional)
):
    # 0️⃣ Rate Limit (only for logged-in users for now)
    if user:
        await rate_limit(user["user_id"])

    try:
        validate_sql(payload.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pool = await get_pool()

    async with pool.acquire() as conn:
        schema_name = None
        try:
            # 1️⃣ Validate problem
            await ensure_problem_exists(conn, payload.problem_id)

            # 2️⃣ Setup isolated schema & data
            schema_name = await setup_execution_schema(conn, payload.problem_id)

            # 3️⃣ Apply execution limits
            await apply_execution_limits(conn)

            # 4️⃣ Execute user query
            user_result = await execute_user_query(conn, payload.query)

            # 5️⃣ Execute reference query (Validation)
            sol_row = await conn.fetchrow(
                "SELECT reference_query, order_sensitive FROM core.problem_solutions WHERE problem_id = $1", 
                payload.problem_id
            )
            
            if not sol_row:
                 # Standard error response if solution is missing configuration
                 return {
                    "status": "error",
                    "user": user_result,
                    "expected": None,
                    "error": "Configuration Error: Reference solution not found",
                    "diff_reason": None
                }

            expected_result = await execute_user_query(conn, sol_row["reference_query"])

            # 6️⃣ Compare
            is_correct, reason = compare_results(
                user_result, 
                expected_result, 
                order_sensitive=sol_row["order_sensitive"]
            )

            # 7️⃣ Record Attempt & Update Streak (Only for logged-in users)
            if user:
                user_id = user["user_id"]
                try:
                    await record_attempt(
                        conn,
                        user_id=user_id,
                        problem_id=payload.problem_id,
                        status="correct" if is_correct else "incorrect",
                        execution_time_ms=user_result["execution_time_ms"]
                    )

                    await update_streak(
                        conn,
                        user_id=user_id,
                        was_correct=is_correct
                    )
                except Exception as e:
                    print(f"Stats recording error: {e}")

            return {
                "status": "correct" if is_correct else "incorrect",
                "user": {
                    "columns": user_result["columns"],
                    "rows": user_result["rows"],
                    "execution_time_ms": user_result["execution_time_ms"],
                },
                "expected": {
                    "columns": expected_result["columns"],
                    "rows": expected_result["rows"],
                },
                "error": None,
                "diff_reason": None if is_correct else reason
            }

        except QueryExecutionError as e:
            return {
                "status": "error",
                "user": None,
                "expected": None,
                "error": str(e),
                "diff_reason": None
            }

        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        finally:
            if schema_name:
                await teardown_execution_schema(conn, schema_name)

