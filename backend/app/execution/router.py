from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import json
from app.execution.validator import validate_code
from app.db import get_pool
from app.execution.schema_manager import (
    setup_execution_schema,
    teardown_execution_schema,
    apply_execution_limits
)
from app.execution.problem_guard import ensure_problem_exists
from app.execution.runner import execute_user_query, QueryExecutionError
from app.execution.judge import compare_results, compare_dsa_results
from app.attempts.service import record_attempt
from app.streaks.service import update_streak
from app.auth.jwt import verify_jwt, verify_jwt_optional
from app.rate_limit.limiter import rate_limit
from app.execution.engines import get_engine
from typing import Optional

router = APIRouter(prefix="/execute", tags=["execution"])

class ExecuteRequest(BaseModel):
    problem_id: str
    query: str
    mode: str = "submit"  # "run" | "submit" — only meaningful for python_dsa


@router.post("")
async def execute_query(
    payload: ExecuteRequest,
    user: Optional[dict] = Depends(verify_jwt_optional)
):
    # 0️⃣ Rate Limit (only for logged-in users for now)
    if user:
        await rate_limit(user["user_id"])

    pool = await get_pool()

    async with pool.acquire() as conn:
        schema_name = None
        try:
            # 1️⃣ Validate problem
            await ensure_problem_exists(conn, payload.problem_id)

            # Fetch problem details to check challenge_type
            prob_row = await conn.fetchrow(
                "SELECT challenge_type FROM core.problems WHERE id = $1", 
                payload.problem_id
            )
            if not prob_row:
                raise HTTPException(status_code=404, detail="Problem not found")
                
            challenge_type = prob_row["challenge_type"]

            # 1.1️⃣ Validate code
            try:
                validate_code(payload.query, challenge_type)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            # 1.5 Check User Profile (Onboarding)
            if user:
                profile_exists = await conn.fetchval(
                    "SELECT onboarding_completed FROM core.users WHERE user_id = $1", 
                    user["user_id"]
                )
                if not profile_exists:
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": "PROFILE_REQUIRED",
                        "diff_reason": "Please complete your profile details to start practicing.",
                        "test_summary": None,
                    }

            # ==========================================
            # 2️⃣ Branch by challenge type
            # ==========================================

            if challenge_type == 'sql':
                # ── SQL Flow ─────────────────────────────────────────────────
                schema_name = await setup_execution_schema(conn, payload.problem_id)
                await apply_execution_limits(conn)
                user_result = await execute_user_query(conn, payload.query)

                sol_row = await conn.fetchrow(
                    "SELECT reference_query, order_sensitive FROM core.problem_solutions WHERE problem_id = $1", 
                    payload.problem_id
                )
                
                if not sol_row:
                     return {
                        "status": "error",
                        "user": user_result,
                        "expected": None,
                        "error": "Configuration Error: Reference solution not found",
                        "diff_reason": None,
                        "test_summary": None,
                    }

                expected_result = await execute_user_query(conn, sol_row["reference_query"])

                is_correct, reason = compare_results(
                    user_result, 
                    expected_result, 
                    order_sensitive=sol_row["order_sensitive"]
                )

                if user:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=user_result["execution_time_ms"],
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                user_result["execution_time_ms"]
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
                    "diff_reason": None if is_correct else reason,
                    "test_summary": None,
                }

            elif challenge_type == 'python_dsa':
                # ── Python DSA Flow ──────────────────────────────────────────
                is_run_mode = (payload.mode == "run")

                # Fetch test cases — "run" mode fetches only sample (non-hidden) cases
                test_case_rows = await conn.fetch(
                    """
                    SELECT input_data, expected, label, is_hidden
                    FROM core.problem_test_cases
                    WHERE problem_id = $1
                      AND (NOT $2 OR is_hidden = false)
                    ORDER BY order_index, created_at
                    """,
                    payload.problem_id,
                    is_run_mode,
                )

                if not test_case_rows:
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": "Configuration Error: No test cases found for this problem.",
                        "diff_reason": None,
                        "test_summary": None,
                    }

                test_cases = [
                    {
                        "input_data": (json.loads(r["input_data"]) if isinstance(r["input_data"], str) else r["input_data"]),
                        "expected":   (json.loads(r["expected"])   if isinstance(r["expected"],   str) else r["expected"]),
                        "label":      r["label"],
                        "is_hidden":  r["is_hidden"],
                    }
                    for r in test_case_rows
                ]

                # Get function name from solution record
                sol_row = await conn.fetchrow(
                    "SELECT function_name FROM core.problem_solutions WHERE problem_id = $1",
                    payload.problem_id
                )
                function_name = (sol_row["function_name"] if sol_row and sol_row["function_name"] else "solve")

                # Run via Python engine (shared runner container, DSA mode)
                engine = get_engine(challenge_type)
                runner_result = await engine.run(
                    payload.query,
                    payload.problem_id,
                    conn,
                    {},
                    test_cases=test_cases,
                    function_name=function_name,
                )

                if runner_result.get("error"):
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": runner_result["error"],
                        "diff_reason": None,
                        "test_summary": None,
                    }

                # Merge input_data back from our test_cases list into the runner
                # results (the runner container only echoes back got/expected/error).
                raw_results = runner_result.get("results", [])
                for i, r in enumerate(raw_results):
                    if i < len(test_cases):
                        r["input_data"] = test_cases[i].get("input_data")

                is_correct, reason, test_summary = compare_dsa_results(raw_results)

                # Record attempt + update streak only on Submit mode
                if user and not is_run_mode:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=runner_result.get("execution_time_ms", 0),
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                runner_result.get("execution_time_ms", 0),
                            )
                    except Exception as e:
                        print(f"Stats recording error: {e}")

                return {
                    # "run_result" signals the frontend this was a dry-run (no badge/streak update)
                    "status": "correct" if is_correct else ("run_result" if is_run_mode else "incorrect"),
                    "user": None,
                    "expected": None,
                    "error": None,
                    "diff_reason": reason,
                    "test_summary": test_summary,
                }

            else:
                # ── Python (Pandas) / PySpark Flow ───────────────────────────
                datasets = await conn.fetch(
                    "SELECT table_name, seed_data_json FROM core.problem_datasets WHERE problem_id = $1",
                    payload.problem_id
                )
                payload_data = {
                    d["table_name"]: (
                        json.loads(d["seed_data_json"]) if isinstance(d["seed_data_json"], str)
                        else d["seed_data_json"]
                    ) if d["seed_data_json"] is not None else {"columns": [], "rows": []}
                    for d in datasets
                }

                engine = get_engine(challenge_type)
                user_result = await engine.run(payload.query, payload.problem_id, conn, payload_data)

                sol_row = await conn.fetchrow(
                    "SELECT reference_output, order_sensitive FROM core.problem_solutions WHERE problem_id = $1", 
                    payload.problem_id
                )
                
                if not sol_row or not sol_row["reference_output"]:
                     return {
                        "status": "error",
                        "user": user_result if not user_result.get("error") else None,
                        "expected": None,
                        "error": "Configuration Error: Pre-computed reference output not found",
                        "diff_reason": None,
                        "test_summary": None,
                    }

                expected_result = sol_row["reference_output"]
                if isinstance(expected_result, str):
                    expected_result = json.loads(expected_result)

                if user_result.get("error"):
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": user_result["error"],
                        "diff_reason": None,
                        "test_summary": None,
                    }

                is_correct, reason = compare_results(
                    user_result, 
                    expected_result, 
                    order_sensitive=sol_row["order_sensitive"]
                )

                if user:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=user_result["execution_time_ms"],
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                user_result["execution_time_ms"]
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
                    "diff_reason": None if is_correct else reason,
                    "test_summary": None,
                }

        except QueryExecutionError as e:
            return {
                "status": "error",
                "user": None,
                "expected": None,
                "error": str(e),
                "diff_reason": None,
                "test_summary": None,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(e))

        finally:
            if schema_name:
                await teardown_execution_schema(conn, schema_name)
